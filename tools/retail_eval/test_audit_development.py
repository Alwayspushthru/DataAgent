import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from audit_development import audit


class DevelopmentAuditTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'captures').mkdir()
        self.save('config.json',dict(split='development',limit=1,cases=['a'],backend_code_sha256='code'))
        self.save('summary.json',dict(selected=1,scores={'off':{},'on':{}}))
        self.save('models.json',{'CHAT':{'model':'fixed'}})
        self.save('server-settings.json',dict(threshold=.2))
        for group in ['off','on']:
            self.save(group+'-score.json',{})
            self.save(group+'-predictions.jsonl',dict(id='a',status='no_execution'))
            capture=dict(caseId='a',group=group,threadId=group,conversationId=group,businessKnowledgeEnabled=group=='on',
                models={'CHAT':{'model':'fixed'}},retrievalSettings=dict(threshold=.2),elapsedMs=10,
                nodes=[dict(node='EVIDENCE_RECALL_NODE',status='completed',
                    outputs={'EVIDENCE':'business rules' if group=='on' else '无'})],sqlExecutions=[])
            self.save('captures/a-'+group+'.json',capture)
        self.freeze=patch('audit_development.check_freeze');self.freeze.start()
        self.addCleanup(self.freeze.stop)

    def save(self,name,value):
        (self.root/name).write_text(json.dumps(value)+'\n')

    def mutate_on(self,key,value):
        name='captures/a-on.json';capture=json.loads((self.root/name).read_text())
        capture[key]=value;self.save(name,capture)

    def test_valid_run_records_off_on_and_hash_evidence(self):
        report=audit(self.root)
        self.assertEqual(report['actual_runs'],2)
        self.assertEqual(report['groups']['off']['nonempty_evidence_runs'],0)
        self.assertEqual(report['groups']['on']['nonempty_evidence_runs'],1)
        self.assertIn('captures/a-on.json',report['files_sha256'])

    def test_stale_off_evidence_in_later_node_is_rejected(self):
        name='captures/a-off.json';capture=json.loads((self.root/name).read_text())
        capture['nodes'].append(dict(node='QUERY_ENHANCE_NODE',status='completed',inputs={'EVIDENCE':'stale business rule'}))
        self.save(name,capture)
        with self.assertRaisesRegex(AssertionError,'contamination'):audit(self.root)

    def test_reused_conversation_run_is_rejected(self):
        self.mutate_on('threadId','off')
        with self.assertRaisesRegex(AssertionError,'reused thread'):audit(self.root)

    def test_model_change_between_groups_is_rejected(self):
        self.mutate_on('models',{'CHAT':{'model':'changed'}})
        with self.assertRaises(AssertionError):audit(self.root)

    def test_reused_conversation_with_unique_threads_is_rejected(self):
        self.mutate_on('conversationId','off')
        with self.assertRaisesRegex(AssertionError,'reused conversation'):audit(self.root)


if __name__=='__main__':unittest.main()
