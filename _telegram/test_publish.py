import unittest
from unittest.mock import patch
import datetime as dt
import publish

class QueueTests(unittest.TestCase):
    def test_slots(self):
        for hour, expected in [(9,None),(10,'morning'),(11,'morning'),(12,None),(17,None),(18,'evening'),(19,'evening'),(20,None)]:
            self.assertEqual(publish.slot_at(dt.datetime(2026,11,16,hour)),expected)

    def test_only_explicit_approval(self):
        state={'posts':{}}
        for approved in [False,'true',1,None]:
            self.assertIsNone(publish.choose([{'id':'a','slot':'morning','approved':approved,'text':'x'}],state,'morning'))

    def test_reservations_and_sent_never_repeat(self):
        posts=[{'id':'a','slot':'morning','approved':True,'text':'x'}]
        for status in ['sending','sent']:
            self.assertIsNone(publish.choose(posts,{'posts':{'a':{'status':status}}},'morning'))

    def test_first_matching_post(self):
        posts=[{'id':'a','slot':'evening','approved':True,'text':'a'},{'id':'b','slot':'morning','approved':True,'text':'b'}]
        self.assertEqual(publish.choose(posts,{'posts':{}},'morning')['id'],'b')

    def test_duplicate_ids_rejected(self):
        with self.assertRaises(ValueError):
            publish.choose([{'id':'a'},{'id':'a'}],{'posts':{}},'morning')

    def test_length_rejected(self):
        with self.assertRaises(ValueError):
            publish.choose([{'id':'a','slot':'morning','approved':True,'text':'x'*4001}],{'posts':{}},'morning')

    def test_network_error_does_not_expose_token(self):
        with patch('urllib.request.urlopen',side_effect=Exception('SECRET')):
            with self.assertRaises(RuntimeError) as caught:
                publish.api('SECRET','getMe',{})
            self.assertNotIn('SECRET',str(caught.exception))

if __name__=='__main__':unittest.main()
