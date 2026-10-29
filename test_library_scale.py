import time
import unittest
from test_app import SecurityTests


class LibraryScaleTests(unittest.TestCase):
    setUp=SecurityTests.setUp
    tearDown=SecurityTests.tearDown
    call=SecurityTests.call
    login=SecurityTests.login

    def test_background_pagination_and_service_responsiveness(self):
        self.login()
        for index in range(1201):
            folder=self.root/f'directory-{index//100}'
            folder.mkdir(exist_ok=True)
            (folder/f'synthetic-{index}.txt').write_text('fixture',encoding='utf-8')
        start=time.monotonic()
        response=self.call('/library?background=1')
        self.assertIn(response.status_code,(200,202))
        self.assertLess(time.monotonic()-start,2)
        self.assertEqual(self.call('/session').status_code,200)
        for _ in range(300):
            response=self.call('/library?background=1')
            if response.status_code==200:
                break
            time.sleep(.02)
        self.assertEqual(response.status_code,200)
        page=response.json
        self.assertEqual(page['total'],1201)
        self.assertEqual(len(page['rows']),500)
        second=self.call('/library?background=1&generation='+page['generation']+'&offset=500').json
        third=self.call('/library?background=1&generation='+page['generation']+'&offset=1000').json
        paths=[r['name'] for r in page['rows']+second['rows']+third['rows']]
        self.assertEqual(len(set(paths)),1201)
        self.assertEqual(self.call('/library?background=1&generation=invalid').status_code,409)
