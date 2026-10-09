import importlib.util, json, tempfile
from pathlib import Path
spec=importlib.util.spec_from_file_location('runner',Path(__file__).with_name('service.py'))
s=importlib.util.module_from_spec(spec); spec.loader.exec_module(s)
def verify(inputs):
    with tempfile.TemporaryDirectory() as d:
        s.ROOT=Path(d); s.init()
        p={'id':'reference-20261008','kind':'paper_20261008','source_csv':(inputs/'source.csv').read_text(),'daily_csv':(inputs/'daily247.csv').read_text(),'table_html':(inputs/'ARK-X_成績表.html').read_text()}
        assert not s.enqueue(p)['duplicate']; assert s.enqueue(p)['duplicate']
        try: s.enqueue(dict(p,source_csv=p['source_csv']+'\n'))
        except ValueError: pass
        else: raise AssertionError('conflict accepted')
        with s.db() as c: c.execute("UPDATE jobs SET state='running',attempts=1")
        s.init(); assert s.run_once()
        with s.db() as c: r=c.execute('SELECT * FROM jobs').fetchone()
        assert r['state']=='done',dict(r)
        result=json.loads(r['result']); assert len(result['rows'])==10
        assert abs(float(result['totalPnlYen'])-27040.3198992058)<0.00001
        assert not s.run_once(); assert s.enqueue(p)['duplicate']
        bad=dict(p,id='bad-data',source_csv='invalid')
        s.enqueue(bad)
        for _ in range(3):
            with s.db() as c: c.execute("UPDATE jobs SET due=0 WHERE id='bad-data'")
            assert s.run_once()
        with s.db() as c: r=c.execute("SELECT state,attempts,result FROM jobs WHERE id='bad-data'").fetchone()
        assert tuple(r)==('failed',3,None)
        print(json.dumps({'duplicate':'PASS','conflict':'PASS','restart_recovery':'PASS','reference_calculation':'PASS','invalid_input_retry_limit':'PASS','cloud_deployed':False}))
if __name__=='__main__':
    import sys
    verify(Path(sys.argv[1]))
