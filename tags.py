"""Local named tags keyed by Windows file identity, independent of folders."""
import json
import os
import secrets
from flask import abort, jsonify, request


def install(app,target,metadata_dir,mutex):
    def location():
        p=metadata_dir('.hotspot-tags')/'tags.json'
        if p.is_symlink() or (p.exists() and getattr(p.lstat(),'st_file_attributes',0)&0x400):
            abort(403)
        return p

    def read():
        p=location()
        return json.loads(p.read_text(encoding='utf-8')) if p.exists() else dict(tags={},files={})

    def write(data):
        p=location()
        tmp=p.with_name(secrets.token_hex(16)+'.tmp')
        try:
            with tmp.open('x',encoding='utf-8') as stream:
                json.dump(data,stream,ensure_ascii=False)
            os.replace(tmp,p)
        finally:
            tmp.unlink(missing_ok=True)

    def identity(p):
        stat=p.stat()
        return f'{stat.st_dev}:{stat.st_ino}:{getattr(stat,"st_birthtime_ns",0)}'

    def name(value):
        if not isinstance(value,str) or not value.strip() or len(value.strip())>40 or any(ord(c)<32 for c in value):
            abort(400)
        return value.strip()

    @app.route('/tags',methods=['GET','POST'])
    def tags():
        with mutex:
            data=read()
            if request.method=='POST':
                body=request.get_json() or {}
                action=body.get('action','create')
                tag=body.get('id')
                if action=='create':
                    label=name(body.get('name'))
                    if any(x.casefold()==label.casefold() for x in data['tags'].values()):
                        abort(409)
                    tag=secrets.token_hex(12)
                    data['tags'][tag]=label
                elif action in ('rename','delete'):
                    if tag not in data['tags']:
                        abort(404)
                    if action=='rename':
                        label=name(body.get('name'))
                        if any(k!=tag and v.casefold()==label.casefold() for k,v in data['tags'].items()):
                            abort(409)
                        data['tags'][tag]=label
                    else:
                        del data['tags'][tag]
                        data['files']={k:[x for x in values if x!=tag] for k,values in data['files'].items()}
                elif action=='assign_many':
                    paths=body.get('paths')
                    adds,removes=body.get('add'),body.get('remove')
                    if not isinstance(paths,list) or not 1<=len(paths)<=2000 or not isinstance(adds,list) or not isinstance(removes,list):
                        abort(400)
                    if any(not isinstance(x,str) or x not in data['tags'] for x in adds+removes):
                        abort(400)
                    keys=[]
                    for path in paths:
                        p=target(path)
                        if not p.is_file():
                            abort(404)
                        keys.append(identity(p))
                    for key in keys:
                        data['files'][key]=sorted((set(data['files'].get(key,[]))-set(removes))|set(adds))
                elif action=='assign':
                    if tag not in data['tags'] or not isinstance(body.get('paths'),list) or len(body['paths'])>2000 or not isinstance(body.get('add'),bool):
                        abort(400)
                    keys=[]
                    for path in body['paths']:
                        p=target(path)
                        if not p.is_file():
                            abort(404)
                        keys.append(identity(p))
                    for key in keys:
                        values=set(data['files'].get(key,[]))
                        if body['add']:
                            values.add(tag)
                        else:
                            values.discard(tag)
                        data['files'][key]=sorted(values)
                else:
                    abort(400)
                write(data)
            return jsonify(tags=data['tags'])

    @app.post('/tag-files')
    def tag_files():
        paths=(request.get_json() or {}).get('paths')
        if not isinstance(paths,list) or len(paths)>100000:
            abort(400)
        with mutex:
            data=read()
            result={}
            for path in paths:
                try:
                    p=target(path)
                    if p.is_file():
                        result[path]=data['files'].get(identity(p),[])
                except OSError:
                    continue
            return jsonify(result)
