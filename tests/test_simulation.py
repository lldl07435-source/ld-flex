import json
from pathlib import Path
import tempfile
import unittest
from ldcell.simulation import Simulation,run_to_end,SCENARIOS
from ldcell.scheduling import Job,choose,make_jobs,POLICIES
from ldcell.storage import RunLog,verify,history,export_run,recover_interrupted,run_folder,canonical
from ldcell.experiments import paired_interval

class SchedulingTests(unittest.TestCase):
    def test_no_future_job_leak(self):
        jobs=[Job(1,0,5,20),Job(2,1,0,30)]
        for policy in POLICIES:
            self.assertEqual(choose(jobs,0,None,policy).id,2)

    def test_release_gate(self):
        for p in POLICIES: self.assertIsNone(choose([Job(1,0,5,8)],0,None,p))

    def test_baseline_order(self):
        jobs=[Job(1,0,0,20),Job(2,1,1,10)]
        self.assertEqual(choose(jobs,2,None,'FIFO').id,1)
        self.assertEqual(choose(jobs,2,None,'EDD').id,2)

    def test_input_rejected(self):
        for seed,count in ((-1,2),(1,0),(1,201)):
            with self.assertRaises(ValueError): make_jobs(seed,count)
        with self.assertRaises(ValueError): Job(1,0,0,float('nan'))

    def test_all_policies_finish_all(self):
        for policy in POLICIES:
            sim=Simulation(count=12,policy=policy);r=run_to_end(sim)
            self.assertEqual(r['completed'],12);self.assertEqual(r['unknown'],0)
            self.assertEqual(len(set(row['order_id'] for row in sim.rows)),12)

    def test_repeatable(self):
        a=Simulation(seed=33,count=8);b=Simulation(seed=33,count=8)
        self.assertEqual(run_to_end(a),run_to_end(b));self.assertEqual(a.rows,b.rows)

    def test_fault_matrix(self):
        expected={'jam':'TIMEOUT','wrong_exit':'WRONG_EXIT','missing_entry':'NO_ENTRY','double_feed':'EXTRA_ITEM','stuck_exit':'TIMEOUT','link_loss':'LINK_LOST','estop':'ESTOP','reboot':'NONE'}
        for scenario in SCENARIOS:
            with self.subTest(scenario=scenario):
                sim=Simulation(count=5,scenario=scenario);r=run_to_end(sim)
                if scenario in expected:
                    unknown=[x for x in sim.rows if x['outcome']=='unknown']
                    self.assertEqual(len(unknown),1);self.assertEqual(unknown[0]['fault'],expected[scenario])
                    self.assertEqual(r['completed'],4)
                else: self.assertEqual(r['completed'],5)
                self.assertEqual(r['releases'],5)

    def test_no_automatic_recovery(self):
        sim=Simulation(count=4,scenario='jam')
        for _ in range(2000): sim.step()
        self.assertTrue(sim.snapshot()['awaiting_recovery'])
        count=len(sim.rows)
        for _ in range(1000): sim.step()
        self.assertEqual(len(sim.rows),count)

    def test_stop_does_not_finish_queue(self):
        sim=Simulation(count=5)
        for _ in range(45): sim.step()
        sim.stop();r=sim.summary()
        self.assertEqual(r['status'],'stopped');self.assertEqual(r['completed'],0);self.assertEqual(r['unknown'],1)

    def test_interval_identical_pairs(self):
        self.assertEqual(paired_interval([0.0]*10),[0.0,0.0])

class StorageTests(unittest.TestCase):
    def setUp(self): self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()

    def test_roundtrip_and_export(self):
        log=RunLog(self.root,{'seed':1});log.event('test',{'x':2});log.finish({'completed':1})
        self.assertTrue(verify(log.folder)['ok']);self.assertEqual(history(self.root)[0]['status'],'completed')
        export_run(log.folder,self.root/'test.zip');self.assertTrue((self.root/'test.zip').is_file())

    def test_changed_event_detected(self):
        log=RunLog(self.root,{});log.finish({})
        p=log.folder/'events.jsonl';p.write_text(p.read_text(encoding='utf-8').replace('created','altered'),encoding='utf-8')
        self.assertFalse(verify(log.folder)['ok'])

    def test_truncation_detected(self):
        log=RunLog(self.root,{});log.finish({})
        p=log.folder/'events.jsonl';p.write_text(p.read_text(encoding='utf-8').splitlines()[0]+'\n',encoding='utf-8')
        self.assertFalse(verify(log.folder)['ok'])

    def test_restart_marks_interrupted(self):
        log=RunLog(self.root,{})
        recover_interrupted(self.root)
        self.assertEqual(history(self.root)[0]['status'],'interrupted');self.assertFalse(verify(log.folder)['ok'])

    def test_path_escape(self):
        with self.assertRaises(ValueError):run_folder(self.root,'../README.md')

    def test_finished_log_not_rewritten(self):
        log=RunLog(self.root,{});log.finish({})
        with self.assertRaises(RuntimeError):log.event('later',{})

    def test_numeric_keys_remain_verifiable(self):
        log=RunLog(self.root,{})
        log.event('task_set',{'times':{1:350,2:400,10:420}})
        log.finish({})
        self.assertTrue(verify(log.folder)['ok'])

    def test_ambiguous_json_keys_rejected(self):
        with self.assertRaises(ValueError):canonical({1:'first','1':'second'})

    def test_rejected_event_does_not_skip_sequence(self):
        log=RunLog(self.root,{})
        with self.assertRaises(ValueError):log.event('bad',{1:'first','1':'second'})
        log.finish({})
        self.assertTrue(verify(log.folder)['ok'])

if __name__=='__main__': unittest.main()
