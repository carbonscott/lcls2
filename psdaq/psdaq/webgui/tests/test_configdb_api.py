"""Tests of psdaq.webgui.configdb_api (the config DB editor's HTTP API) against the campaign's
config DB stand-in (psdaq.sim.configdb_server) on 127.0.0.1, through the web GUI server in --emulate mode.

Run with tests/run_webgui_tests.sh -k configdb_api (the server and the stand-in use the DAQ env's python).
"""

import json
import subprocess
import urllib.error
import urllib.request

import pytest

from webgui_harness import ServerProc, run_server_cmd, SERVER_PYTHON, server_env  # noqa: F401
from configeditor_harness import ConfigDbProc, seeded_store, SERNO


@pytest.fixture
def cfgdb(tmp_path):
    db = ConfigDbProc(seeded_store(tmp_path)).start()
    yield db
    db.stop()


@pytest.fixture
def web(cfgdb):
    s = ServerProc(['--emulate', '--configdb-url', cfgdb.url]).start()
    yield s
    s.stop()


def cfg(web, alias, device, **kw):
    q = '&'.join('%s=%s' % kv for kv in [('alias', alias), ('device', device)] + sorted(kw.items()))
    return web.get('/api/configdb/config?' + q)


def leaves(tree):
    out = {}
    for n in tree:
        if n.get('leaf'):
            out[n['path']] = n
        else:
            out.update(leaves(n.get('children', [])))
    return out


def node(tree, *keys):
    for k in keys:
        tree = [n for n in tree if n.get('key') == k]
        assert tree, 'no node %s' % (keys,)
        n = tree[0]
        tree = n.get('children', [])
    return n


def test_info_resolves_hutch(web, cfgdb):
    info = web.get('/api/configdb/info')
    assert info['ok'] and info['url'] == cfgdb.url and info['root'] == 'configDB'
    assert info['instrument'] == 'TST'          # what the emulator's getInstrument reports
    assert info['hutch'] == 'tst'               # the stand-in's hutch, matched without case


def test_aliases_and_devices(web):
    a = web.get('/api/configdb/aliases')
    assert a['ok'] and not a['fallback'] and sorted(a['aliases']) == ['BEAM', 'NOBEAM'] and a['hutch'] == 'tst'
    d = web.get('/api/configdb/devices?alias=BEAM')
    assert d['ok'] and d['devices'] == ['fakecam_0', 'tmoteb_0', 'treetest_0']
    assert web.get('/api/configdb/devices?alias=NOBEAM')['devices'] == []


def test_config_fakecam_as_the_tree_shows_it(web):
    j = cfg(web, 'BEAM', 'fakecam_0')
    assert j['ok'] and j['title'] == 'Config Editor for BEAM fakecam_0'
    c = json.loads(j['config_json'])
    assert c['detName:RO'] == 'fakecam_0' and c['user']['sim_seed'] == 0x1234
    # :RO keys and :types: are hidden, except help:RO whose value is read only (CGWConfigEditorTree.py:161-165)
    # in the DB's key order (the stand-in stores sorted keys), minus the hidden ones
    assert [n['key'] for n in j['tree']] == [k for k in c if k != ':types:' and (':RO' not in k or k == 'help:RO')]
    assert sorted(n['key'] for n in j['tree']) == ['expert', 'help:RO', 'user']
    lv = leaves(j['tree'])
    assert lv['help:RO']['enabled'] is False and lv['help:RO']['editable'] is False
    s = lv['user.sim_seed']
    assert (s['text'], s['dtype'], s['checkable'], s['editable'], s['cell']) == ('4660', 'UINT32', True, True, 'data')
    assert node(j['tree'], 'user')['text'] == 'user *'
    # the Text editor shows str_json (CGJsonUtils.py:248-251)
    assert j['text'] == json.dumps(c, indent=4, separators=(', ', ': '))


def test_config_tree_kinds(web):
    j = cfg(web, 'BEAM', 'treetest_0')
    lv = leaves(j['tree'])
    assert lv['user.enable']['enum'] == [['False', 0], ['True', 1]] and lv['user.enable']['text'] == 'True'
    enum = json.loads(j['config_json'])[':types:'][':enum:']['modeEnum']      # in the DB's order
    assert lv['user.mode']['enum'] == [[k, v] for k, v in enum.items()] and lv['user.mode']['text'] == 'Off'
    assert sorted(lv['user.mode']['enum'], key=lambda p: p[1]) == [['Fast', 0], ['Slow', 1], ['Off', 2]]
    sh = lv['user.short']
    assert (sh['cell'], sh['text'], sh['editable'], sh['trimmed'], sh['descr']) == ('list', '1 2 3', True, False, 'list')
    lo = lv['user.long']
    assert lo['text'] == '10 11 12 13 14 ...' and lo['full'] == ' '.join(str(i) for i in range(10, 22))
    assert lo['editable'] is False and lo['trimmed'] and lo['descr'] == 'trimmed list'
    assert lv['expert.big']['text'] == str(2 ** 63 + 5)                 # no float rounding
    assert lv['user.offset']['checkable'] and not lv['user.ratio']['checkable']
    assert lv['user.label']['text'] == 'cam A'
    assert 'expert.secret:RO' not in lv
    chan = node(j['tree'], 'expert', 'chan')
    assert chan['kind'] == 'listc' and [c['key'] for c in chan['children']] == ['0', '1']
    assert all(c['cell'] == 'index' for c in chan['children'])
    assert lv['expert.chan.1.gain']['text'] == '2'


def test_save_tree_hex_bad_status_and_uint64(web):
    r = web.post('/api/configdb/save', {'alias': 'BEAM', 'device': 'fakecam_0', 'mode': 'tree',
                                        'config_json': cfg(web, 'BEAM', 'fakecam_0')['config_json'],
                                        'leaves': [['user.sim_seed', '0x2a2a']]})
    assert r['ok'] and r['bad'] == [] and isinstance(r['key'], int)
    assert json.loads(cfg(web, 'BEAM', 'fakecam_0')['config_json'])['user']['sim_seed'] == 0x2a2a
    big = 2 ** 63 + 6
    r = web.post('/api/configdb/save', {'alias': 'BEAM', 'device': 'treetest_0', 'mode': 'tree',
                                        'config_json': cfg(web, 'BEAM', 'treetest_0')['config_json'],
                                        'leaves': [['user.gain', '300'], ['expert.big', str(big)],
                                                   ['user.mode', '1'], ['user.short', '4 5 6']]})
    assert r['ok'] and r['bad'] == [{'path': 'user.gain', 'value': '300', 'status': 2}]   # UINT8 range
    c = json.loads(cfg(web, 'BEAM', 'treetest_0')['config_json'])
    assert c['user']['gain'] == 7 and c['expert']['big'] == big and c['user']['mode'] == 1
    assert c['user']['short'] == [4, 5, 6]
    log = [x['msg'] for x in web.get('/api/log')['records']]
    assert any('updateValue path:[user.gain] new value: 300 bad status: 2' in m for m in log)


def test_save_text_mode_and_bad_text(web):
    j = cfg(web, 'BEAM', 'fakecam_0')
    text = j['text'].replace('"sim_seed": 4660', '"sim_seed": 4242')
    assert text != j['text']
    r = web.post('/api/configdb/save', {'alias': 'BEAM', 'device': 'fakecam_0', 'mode': 'text', 'text': text})
    assert r['ok']
    assert json.loads(cfg(web, 'BEAM', 'fakecam_0')['config_json'])['user']['sim_seed'] == 4242
    r = web.post('/api/configdb/save', {'alias': 'BEAM', 'device': 'fakecam_0', 'mode': 'text', 'text': '{oops'})
    assert not r['ok'] and 'not valid JSON' in r['err_info']


def test_save_unchanged_is_an_error_in_the_log(web):
    j = cfg(web, 'BEAM', 'fakecam_0')
    r = web.post('/api/configdb/save', {'alias': 'BEAM', 'device': 'fakecam_0', 'mode': 'tree',
                                        'config_json': j['config_json'], 'leaves': []})
    assert not r['ok'] and r['err_info'].startswith('Exception: ')     # CGWMainConfiguration.py:139-140
    errs = [x['msg'] for x in web.get('/api/log')['records'] if x['level'] == 'ERROR']
    assert any(m.startswith('Exception: modify_device') for m in errs)


def test_bad_names_refused(web):
    assert 'bad alias' in web.get('/api/configdb/devices?alias=../x')['err_info']
    assert 'bad device' in cfg(web, 'BEAM', 'a/b')['err_info']
    assert 'missing parameter' in web.get('/api/configdb/config?alias=BEAM')['err_info']


def test_no_configdb_url_means_no_editor():
    s = ServerProc(['--emulate']).start()
    try:
        info = s.get('/api/configdb/info')
        assert not info['ok'] and 'no --configdb-url' in info['err_info']
        a = s.get('/api/configdb/aliases')
        assert not a['ok'] and 'no --configdb-url given' in a['err_info']
    finally:
        s.stop()


def test_non_local_configdb_url_refused():
    r = run_server_cmd(['--emulate', '--configdb-url', 'https://pswww.slac.stanford.edu/ws-auth/devconfigdb/ws/',
                        '--print-config'])
    assert r.returncode == 2 and 'not a loopback address' in r.stderr
    # the module refuses on its own too, before any request (requests.get would raise if called)
    code = r'''
import json, types, requests
def boom(*a, **k): raise AssertionError('a request was made: %r' % (a,))
requests.get = boom
from psdaq.webgui.configdb_api import ConfigDbApi
args = types.SimpleNamespace(configdb_url='http://10.1.2.3/ws/', configdb_root='configDB', user='u')
api = ConfigDbApi(types.SimpleNamespace(args=args))
print(json.dumps([api.info({})[1], api.aliases({})[1], api.devices({'alias': ['BEAM']})[1]]))
'''
    p = subprocess.run([SERVER_PYTHON, '-c', code], env=server_env(), stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout.strip().splitlines()[-1])
    for rep in out:
        assert rep['ok'] is False and 'not a loopback address' in rep['err_info']


def test_npy_roundtrip(web):
    import base64
    r = web.post('/api/configdb/npy_save', {'text': '1 2 3.5'})
    raw = base64.b64decode(r['data_b64'])
    assert r['ok'] and raw[:6] == b'\x93NUMPY'
    back = web.post('/api/configdb/npy_load', {'data_b64': r['data_b64']})
    assert back['ok'] and [float(x) for x in back['text'].split()] == [1.0, 2.0, 3.5]


def test_note_logs_and_unknown_event(web):
    assert web.post('/api/configdb/note', {'event': 'save_cancelled'})['ok']
    log = web.get('/api/log')['records']
    assert any(x['level'] == 'WARNING' and x['msg'] == 'Saving of configuration in DB is cancelled...' for x in log)
    req = urllib.request.Request(web.url + 'api/configdb/note', data=b'{"event": "rm -rf"}',
                                 headers={'Content-Type': 'application/json'}, method='POST')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with pytest.raises(urllib.error.HTTPError) as ei:
        opener.open(req, timeout=10)
    assert ei.value.code == 400


def test_serial_number_db_merge(web):
    on = json.loads(cfg(web, 'BEAM', 'fakecam_0', use_serial_db='1', serno=SERNO)['config_json'])
    # update_config(sn_config, alias_config): the S/N DB values win, :RO keys stay the alias's
    assert on['expert']['sim_length'] == 2048 and on['user']['sim_seed'] == 0x5555
    assert on['use_serial_db'] is True and on['detName:RO'] == 'fakecam_0'
    off = json.loads(cfg(web, 'BEAM', 'fakecam_0', use_serial_db='0')['config_json'])
    assert off['expert']['sim_length'] == 1024 and off['use_serial_db'] is False
    bad = cfg(web, 'BEAM', 'fakecam_0', use_serial_db='1', serno='nosuch_0')
    assert not bad['ok']


def test_render_and_content(web):
    j = cfg(web, 'BEAM', 'fakecam_0')
    r = web.post('/api/configdb/render', {'text': j['text']})
    assert r['ok'] and r['tree'] == j['tree']
    c = web.post('/api/configdb/content', {'mode': 'tree', 'config_json': j['config_json'],
                                           'leaves': [['expert.sim_length', '0x800']]})
    assert c['ok'] and '"sim_length": 2048' in c['text']
    t = web.post('/api/configdb/content', {'mode': 'text', 'text': c['text']})
    assert t['ok'] and leaves(t['tree'])['expert.sim_length']['text'] == '2048'
