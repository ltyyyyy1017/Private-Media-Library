import unittest
from test_app import SecurityTests
from app import create_app


class TagTests(unittest.TestCase):
    setUp=SecurityTests.setUp
    tearDown=SecurityTests.tearDown
    call=SecurityTests.call
    login=SecurityTests.login

    def test_tags_survive_move_delete_restore_restart(self):
        self.login()
        (self.root/'a.mp4').write_bytes(b'synthetic video')
        (self.root/'folder').mkdir()
        self.assertEqual(self.call('/tags','POST',json={'name':'旅行'}).status_code,200)
        id=next(iter(self.call('/tags').json['tags']))
        self.assertEqual(self.call('/tags','POST',json={'name':'旅行'}).status_code,409)
        self.assertEqual(self.call('/tags','POST',json={'action':'assign','id':id,'paths':['a.mp4'],'add':True}).status_code,200)
        self.assertEqual(self.call('/move','POST',json={'path':'a.mp4','new':'folder/b.mp4'}).status_code,200)
        self.assertEqual(self.call('/tag-files','POST',json={'paths':['folder/b.mp4']}).json['folder/b.mp4'],[id])
        self.call('/delete','POST',json={'path':'folder/b.mp4'})
        history=self.call('/history').json
        self.assertEqual(self.call('/undo','POST',json={'id':history[0]['id']}).status_code,200)
        self.app=create_app(self.root,'192.168.137.0/24','test-password-12345');self.client=self.app.test_client();self.login()
        self.assertEqual(self.call('/tag-files','POST',json={'paths':['folder/b.mp4']}).json['folder/b.mp4'],[id])
        self.call('/tags','POST',json={'action':'rename','id':id,'name':'假期'})
        self.assertEqual(self.call('/tags').json['tags'][id],'假期')
        self.call('/tags','POST',json={'action':'delete','id':id})
        self.assertEqual(self.call('/tag-files','POST',json={'paths':['folder/b.mp4']}).json['folder/b.mp4'],[])
        self.assertTrue((self.root/'folder/b.mp4').is_file())

    def test_tags_protection(self):
        self.assertEqual(self.call('/tags').status_code,401)
        self.login()
        self.assertEqual(self.call('/tags',ip='10.0.0.2').status_code,403)
        self.assertEqual(self.call('/tags','POST',json={'name':' '}).status_code,400)
        self.call('/tags','POST',json={'name':'test'})
        id=next(iter(self.call('/tags').json['tags']))
        self.assertEqual(self.call('/tags','POST',json={'action':'assign','id':id,'paths':['../secret'],'add':True}).status_code,400)

    def test_multi_tag_assignment(self):
        self.login()
        for filename in ('a.mp4','b.mp4'):
            (self.root/filename).write_bytes(b'synthetic')
        for label in ('旅行','收藏','待看'):
            self.call('/tags','POST',json={'name':label})
        ids=list(self.call('/tags').json['tags'])
        self.call('/tags','POST',json={'action':'assign_many','paths':['a.mp4','b.mp4'],'add':ids[:2],'remove':[]})
        values=self.call('/tag-files','POST',json={'paths':['a.mp4','b.mp4']}).json
        self.assertEqual(set(values['a.mp4']),set(ids[:2]))
        self.assertEqual(set(values['b.mp4']),set(ids[:2]))
        self.call('/tags','POST',json={'action':'assign_many','paths':['a.mp4'],'add':[ids[2]],'remove':[ids[0]]})
        values=self.call('/tag-files','POST',json={'paths':['a.mp4','b.mp4']}).json
        self.assertEqual(set(values['a.mp4']),{ids[1],ids[2]})
        self.assertEqual(set(values['b.mp4']),set(ids[:2]))
