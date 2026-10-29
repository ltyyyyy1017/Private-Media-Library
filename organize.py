"""Local-only library browsing, byte-exact duplicates and reversible operations."""
import hashlib
import json
import os
import secrets
import threading
import time
from collections import defaultdict
from flask import abort, jsonify, request


def install(app, root, target, metadata_dir, mutex, favorites_read, favorites_write):
    def safe_metadata(p):
        for node in (p, *p.parents):
            if node == root:
                break
            if node.is_symlink() or (node.exists() and getattr(node.lstat(), 'st_file_attributes', 0) & 0x400):
                abort(403)
        return p

    def history_file():
        return safe_metadata(metadata_dir('.hotspot-organize') / 'history.json')

    def read():
        p = history_file()
        return json.loads(p.read_text(encoding='utf-8')) if p.exists() else []

    def save(rows):
        p = history_file()
        tmp = p.with_name(secrets.token_hex(16) + '.tmp')
        try:
            with tmp.open('x', encoding='utf-8') as stream:
                json.dump(rows, stream, ensure_ascii=False)
            os.replace(tmp, p)
        finally:
            tmp.unlink(missing_ok=True)

    def identity(p):
        s = p.stat()
        return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns]

    def record(old, new, destination, favorites, trash=False):
        rows = read()
        rows.append(dict(id=secrets.token_hex(16), old=old, new=new, trash=trash,
                         identity=identity(destination), favorites=sorted(favorites), time=time.time()))
        save(rows)

    @app.get('/history')
    def history():
        with mutex:
            return jsonify([{k: row[k] for k in ('id','old','new','trash','time')} for row in reversed(read())])

    @app.post('/undo')
    def undo():
        with mutex:
            rows = read()
            if not rows or rows[-1]['id'] != (request.get_json() or {}).get('id'):
                abort(409, 'Undo the most recent operation first.')
            row = rows[-1]
            destination = target(row['old'])
            source = safe_metadata(root / row['new']) if row['trash'] else target(row['new'])
            if not source.exists() or destination.exists() or not destination.parent.is_dir():
                abort(409)
            if identity(source) != row['identity']:
                abort(409, 'File changed since operation; restore manually.')
            values = favorites_read()
            updated = set(values)
            if not row['trash']:
                updated = {row['old'] + x[len(row['new']):] if x == row['new'] or x.startswith(row['new']+'/') else x for x in values}
            updated.update(row['favorites'])
            source.rename(destination)
            try:
                favorites_write(updated)
                save(rows[:-1])
            except Exception:
                destination.rename(source)
                favorites_write(values)
                raise
            return jsonify(ok=True)

    def walk():
        # No symlinks/junctions, hidden application state, or external folders.
        stack = [root]
        while stack:
            folder = stack.pop()
            try:
                children = list(folder.iterdir())
            except OSError:
                continue
            for child in children:
                if child.name.lower().startswith('.hotspot-'):
                    continue
                try:
                    path = child.relative_to(root).as_posix()
                    child = target(path)
                    if child.is_dir():
                        stack.append(child)
                    elif child.is_file():
                        stat = child.stat()
                        yield dict(name=path, directory=False, size=stat.st_size, modified=stat.st_mtime)
                except Exception as exc:
                    if isinstance(exc, OSError) or getattr(exc, 'code', None):
                        continue
                    raise

    @app.get('/library')
    def library():
        return jsonify(list(walk()))

    results_file=safe_metadata(metadata_dir('.hotspot-organize')/'duplicates.json')
    state = dict(running=False, phase='尚未扫描', checked=0, total=0, groups=[], skipped=0)
    if results_file.exists():
        try:
            saved=json.loads(results_file.read_text(encoding='utf-8'))
            state.update(saved,running=False)
        except (ValueError,OSError):
            pass
    scan_lock = threading.Lock()

    @app.get('/duplicates')
    def duplicates():
        with scan_lock:
            snapshot=dict(state)
            snapshot['groups']=[]
            for group in state['groups']:
                paths=[]
                for path in group['paths']:
                    try:
                        if target(path).is_file():
                            paths.append(path)
                    except Exception:
                        continue
                if len(paths)>1:
                    snapshot['groups'].append(dict(group,paths=paths))
            return jsonify(snapshot)

    @app.post('/duplicates')
    def start_duplicates():
        include_similar=(request.get_json() or {}).get('similar') is True
        with scan_lock:
            if state['running']:
                return jsonify(running=True), 202
            state.update(running=True, phase='按大小筛选', checked=0, total=0, groups=[], skipped=0)

        def scan():
            with app.app_context():
                try:
                    sizes = defaultdict(list)
                    files=list(walk())
                    for f in files:
                        sizes[f['size']].append(f['name'])
                    candidates = [names for names in sizes.values() if len(names)>1]
                    with scan_lock:
                        state.update(total=sum(map(len,candidates)), phase='SHA-256 与逐字节校验')
                    groups = []
                    for names in candidates:
                        hashes = defaultdict(list)
                        for name in names:
                            try:
                                p = target(name)
                                before = identity(p)
                                digest = hashlib.sha256()
                                with p.open('rb') as stream:
                                    while chunk := stream.read(1024*1024):
                                        digest.update(chunk)
                                if identity(p) != before:
                                    raise OSError('changed')
                                hashes[digest.digest()].append((name,before))
                            except OSError:
                                with scan_lock:
                                    state['skipped'] += 1
                            finally:
                                with scan_lock:
                                    state['checked'] += 1
                        for bucket in hashes.values():
                            if len(bucket)<2:
                                continue
                            first, signature = bucket[0]
                            equal = [first]
                            for name, expected in bucket[1:]:
                                try:
                                    a,b = target(first),target(name)
                                    if identity(a)!=signature or identity(b)!=expected:
                                        continue
                                    same=True
                                    with a.open('rb') as x, b.open('rb') as y:
                                        while True:
                                            left,right=x.read(1024*1024),y.read(1024*1024)
                                            if left!=right:
                                                same=False
                                                break
                                            if not left:
                                                break
                                    if same and identity(a)==signature and identity(b)==expected:
                                        equal.append(name)
                                except OSError:
                                    continue
                            if len(equal)>1:
                                groups.append(dict(paths=equal,size=signature[2]))
                    if include_similar:
                        from similarity import find_candidates
                        cache_file=safe_metadata(metadata_dir('.hotspot-organize')/'fingerprints.json')
                        try:
                            cache=json.loads(cache_file.read_text(encoding='utf-8')) if cache_file.exists() else {}
                        except (ValueError,OSError):
                            cache={}
                        def progress(done,total):
                            with scan_lock:
                                state.update(phase='本地相似媒体比对',checked=done,total=total)
                        candidates,skipped=find_candidates(files,target,cache,progress)
                        exact_pairs={frozenset(g['paths']) for g in groups}
                        groups.extend(g for g in candidates if frozenset(g['paths']) not in exact_pairs)
                        cache_file.write_text(json.dumps(cache),encoding='utf-8')
                        with scan_lock:
                            state['skipped']+=skipped
                    with scan_lock:
                        state.update(groups=groups, phase='扫描完成 · 结果已保留',checked=state['total'])
                        temporary=results_file.with_suffix('.tmp')
                        temporary.write_text(json.dumps(dict(state,running=False),ensure_ascii=False),encoding='utf-8')
                        os.replace(temporary,results_file)
                except Exception:
                    with scan_lock:
                        state.update(phase='扫描中断，请重试')
                finally:
                    with scan_lock:
                        state['running']=False
        threading.Thread(target=scan,daemon=True,name='local-duplicates').start()
        return jsonify(running=True),202

    return record
