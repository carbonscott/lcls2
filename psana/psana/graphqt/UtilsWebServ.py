#!/usr/bin/env python

"""
Usage ::

    import psana.graphqt.UtilsWebServ as uws

Created on 2021-08-09 by Mikhail Dubrovin
"""

import logging
logger = logging.getLogger(__name__)

import sys
import requests
import json
import kerberos
from krtc import KerberosTicket
logger = logging.getLogger(__name__)


def kerberos_headers(serv='HTTP@pswww.slac.stanford.edu'):
    """Return Kerberos authentication headers for the service ``serv``.

    Calls ``KerberosTicket(serv).getAuthHeaders()``. On ``kerberos.GSSError`` it logs a warning, prints an exit message and calls ``sys.exit()``; the second ``except err:`` clause names an undefined variable, so any other exception ends in a NameError instead.

    Parameters
    ----------
    serv : str
        Kerberos service name, default 'HTTP@pswww.slac.stanford.edu'.

    Returns
    -------
    object
        The headers returned by ``getAuthHeaders()``.
    """
    try:
      krbheaders = KerberosTicket(serv).getAuthHeaders()
    except kerberos.GSSError as err:
      logger.warning(str(err))
      msg = '\nEXIT: CHECK VALIDITI OF KERBEROS TICKET (commands klist, kinit)'
      print(msg)
      sys.exit()
    except err:
      logger.warning(str(err))
      msg = '\nEXIT: UNSPECIFIED ERROR at getting KerberosTicket'
      print(msg)
      sys.exit()
    return krbheaders


def json_pro(r):
    """Return ``r.json()`` if the response ``r`` is truthy.

    Otherwise log a warning and return None.
    """
    if r: return r.json()
    logger.warning('unexpected responce from requests.get:\n%s' % str(r))
    return None


def value_from_json(jo):
    """Return ``jo['value']`` when ``jo['success']`` is true.

    Returns None if ``jo`` is None, or logs a warning with the dumped JSON and returns None when ``jo['success']`` is false.
    """
    if jo is None: return None
    if jo['success']:
        return jo['value']
    else:
        logger.warning('unsuccessful responce from requests.get:\n%s' % json.dumps(jo, indent=2))
        return None


def value_from_responce(r):
    """Return the 'value' field of the JSON in response ``r``, or None.

    Equivalent to ``value_from_json(json_pro(r))``.
    """
    return value_from_json(json_pro(r))


def value_for_request(ws_url, params={}):
    """Send a Kerberos-authenticated GET request and return the 'value' field of the reply.

    Calls ``requests.get(ws_url, headers=kerberos_headers(), params=params, timeout=180)`` and passes the response to ``value_from_responce``.

    Parameters
    ----------
    ws_url : str
        Web-service URL.
    params : dict
        Query parameters, default empty.

    Returns
    -------
    object or None
        The 'value' field of the JSON reply, or None on an unsuccessful reply.
    """
    logger.debug('ws_url: %s' % ws_url)
    # cpo: add timeout here to debug intermittent hang in github actions
    r = requests.get(ws_url, headers=kerberos_headers(), params=params, timeout=180)
    return value_from_responce(r)


# curl -s "https://pswww.slac.stanford.edu/ws/lgbk/lgbk/xpptut15/ws/files_for_live_mode_at_location?location=SLAC"
def json_runs(expname, location='SLAC'):
    """Return the logbook 'files_for_live_mode_at_location' value for experiment ``expname``.

    Asserts that ``expname`` is a str of length 8 or 9, sends a Kerberos-authenticated GET (timeout 180 s) to the pswww ws-kerb lgbk URL with the given ``location`` and returns ``value_from_responce`` of the reply.

    Returns
    -------
    object or None
        The 'value' field of the reply, or None on failure.
    """
    assert isinstance(expname, str)
    assert len(expname) in (8,9)
    ws_url = "https://pswww.slac.stanford.edu/ws-kerb/lgbk/lgbk/%s/ws/files_for_live_mode_at_location?location=%s"%\
             (expname, location)
    # cpo: add timeout here to debug intermittent hang in github actions
    r = requests.get(ws_url, headers=kerberos_headers(), timeout=180)
    return value_from_responce(r)


def run_info_selected(expname, location='SLAC'):
    """Return a dict mapping run number to (begin_time, end_time, is_closed, all_present).

    The dict is built from the records returned by ``json_runs(expname, location)``; returns None if that call returns None.
    """
    joruns = json_runs(expname, location)
    if joruns is None: return None
    return {d['run_num']: (d['begin_time'], d['end_time'], d['is_closed'], d['all_present']) for d in joruns}


def runnums_with_tag(expname, tag='DARK'):
    """Request the logbook 'get_runs_with_tag' service for ``tag`` and return its value.

    The URL uses the 'ws/lgbk' path; the request is sent through ``value_for_request``, so None is returned on failure.
    """
    ws_url = "https://pswww.slac.stanford.edu/ws/lgbk/lgbk/%s/ws/get_runs_with_tag?tag=%s" % (expname, tag)
    return value_for_request(ws_url)


def run_table_data(expname):
    """Request the logbook 'run_table_data' service for ``expname`` with tableName 'Scan Table' and return its value, or None."""
    ws_url = "https://pswww.slac.stanford.edu/ws-kerb/lgbk/lgbk/%s/ws/run_table_data" % expname
    return value_for_request(ws_url, params={"tableName": "Scan Table"})


def run_parameters(expname, runnum):
    """Request the logbook record 'runs/<runnum>' for ``expname`` and return its value, or None.

    ``runnum`` is formatted into the URL with ``%d``.
    """
    ws_url = "https://pswww.slac.stanford.edu/ws-kerb/lgbk/lgbk/%s/ws/runs/%d" % (expname, runnum)
    return value_for_request(ws_url)


def detnames(expname, runnum):
    """Return detector names listed in the run parameters.

    Takes the keys of ``run_parameters(expname, runnum).get('params', {})`` that start with 'DAQ Detectors/' and returns, for each, the part after the last '/'. Raises AttributeError if ``run_parameters`` returns None.

    Returns
    -------
    list of str
    """
    jo = run_parameters(expname, runnum)
    return [k.split('/')[-1] for k, v in jo.get("params", {}).items() if k.startswith("DAQ Detectors/")]


def runinfo_for_params(expname, params={"includeParams": "true"}):
    """Request the logbook 'runs' list for ``expname`` with query ``params`` and return its value, or None."""
    ws_url = "https://pswww.slac.stanford.edu/ws-kerb/lgbk/lgbk/%s/ws/runs" % (expname)
    return value_for_request(ws_url, params=params)


def run_numbers_at_location(expname, location='SLAC'):
    """Return the sorted 'run_num' values of ``json_runs(expname, location)``.

    Returns None if ``json_runs`` returns None.
    """
    joruns = json_runs(expname, location)
    if joruns is None: return None
    return sorted([d['run_num'] for d in joruns])


def run_numbers(expname):
    """Return the sorted 'num' values of ``runinfo_for_params(expname, params={'includeParams': 'false'})``.

    Returns None if that request returns None.
    """
    jo = runinfo_for_params(expname, params={"includeParams": "false"})
    if jo is None: return None
    return sorted([d['num'] for d in jo])


def run_files(expname, runnum):
    """Request the logbook '<runnum>/files' list for ``expname`` and return its value, or None."""
    ws_url = "https://pswww.slac.stanford.edu/ws-kerb/lgbk/lgbk/%s/ws/%d/files" % (expname, runnum)
    return value_for_request(ws_url)


def exp_tags(expname):
    """Request the logbook 'get_elog_tags' service for ``expname`` and return its value, or None."""
    ws_url = "https://pswww.slac.stanford.edu/ws-kerb/lgbk/lgbk/%s/ws/get_elog_tags" % expname
    return value_for_request(ws_url)


def runs_to_tags(expname):
    """Request the logbook 'get_runs_to_tags' service for ``expname`` and return its value, or None."""
    ws_url = "https://pswww.slac.stanford.edu/ws-kerb/lgbk/lgbk/%s/ws/get_runs_to_tags" % expname
    return value_for_request(ws_url)


def tags_to_runs(expname):
    """Request the logbook 'get_tags_to_runs' service for ``expname`` and return its value, or None."""
    ws_url = "https://pswww.slac.stanford.edu/ws-kerb/lgbk/lgbk/%s/ws/get_tags_to_runs" % expname
    return value_for_request(ws_url)


def tags_for_run(expname, runnum):
    """Request the logbook '<runnum>/get_tags_for_run' service for ``expname`` and return its value, or None."""
    ws_url = "https://pswww.slac.stanford.edu/ws-kerb/lgbk/lgbk/%s/ws/%d/get_tags_for_run" % (expname, runnum)
    return value_for_request(ws_url)


def exprun_tags(expname):
    """returns dict {runnum: <list-of-tags>}"""
    d = {k:[] for k in run_numbers(expname)}
    tags = exp_tags(expname)
    if tags:
      for tag in tags:
        if tag:
         for rnum in runnums_with_tag(expname, tag=tag):
           d[rnum].append(tag)
    return d


def is_lcls2(expname, runnum=None):

    """Return True if the path of the first file of a run ends with 'xtc2'.

    If ``runnum`` is None the first entry of ``run_numbers(expname)`` is used. Returns None with a warning if no run numbers or no files are found; a file record without 'path' raises TypeError in the debug log call, which slices ``path[-4:]`` before the path is checked.

    Returns
    -------
    bool or None
    """
    rnum1 = runnum
    if runnum is None:
      rnums = run_numbers(expname)
      if not rnums:
        logger.warning('issue with run_numbers("%s"): %s' % (expname, str(rnums)))
        return None
      rnum1 = rnums[0]

    files = run_files(expname, rnum1)
    if not files:
        logger.warning('issue with run_files("%s", %d): %s' % (expname, rnum1, str(files)))
        return None
    if len(files)<1:
        logger.warning('issue with run_files("%s", %d) length: %s' % (expname, rnum1, str(files)))
        return None
    dicfile = files[0]
    path = dicfile.get('path',None)
    logger.debug('expname:%s runnum:%d path:%s extension:%s' % (expname, rnum1, path, path[-4:]))
    if not path:
        logger.warning('expname:%s runnum:%d issue with path:%s' % (expname, rnum1, str(path)))
    return path[-4:]=='xtc2'


if __name__ == "__main__":

  def test_run_parameters(expname, runnum):
    """Print ``run_parameters(expname, runnum)`` as indented JSON if it is truthy."""
    jo = run_parameters(expname, runnum)
    if jo: print(json.dumps(jo, indent=2))


  def test_all_runs_with_par_value():
    """POST a fixed parameter-match query for experiment 'xcsdaq13' to 'get_runs_matching_params' and print the JSON reply if the response is truthy."""
    ws_url = "https://pswww.slac.stanford.edu/ws-kerb/lgbk/lgbk/{experiment_name}/ws/get_runs_matching_params".format(experiment_name="xcsdaq13")
    krbheaders = KerberosTicket("HTTP@pswww.slac.stanford.edu").getAuthHeaders()
    r = requests.post(ws_url, headers=krbheaders, json={"USEG:UND1:3250:KACT": "3.47697", "XCS:R42:EVR:01:TRIG7:BW_TDES": "896924"})
    if r: print(r.json())


  def test_jsinfo_runs(expname, location='SLAC'):
    """Print ``json_runs(expname, location)`` as indented JSON, or its str() if it is falsy."""
    jo = json_runs(expname, location)
    print(json.dumps(jo, indent=2) if jo else str(jo))


  def test_run_numbers_at_location(expname, location='SLAC'):
    """Print the result of ``run_numbers_at_location(expname, location)``."""
    print('test_run_numbers_at_location:', run_numbers_at_location(expname, location))


  def test_run_numbers(expname):
    """Print the result of ``run_numbers(expname)``."""
    print('run numbers:', run_numbers(expname))


  def test_exp_tags(expname):
    """Print the result of ``exp_tags(expname)``."""
    print(exp_tags(expname))


  def test_exprun_tags(expname):
    """Print the result of ``exprun_tags(expname)``."""
    print(exprun_tags(expname))


  def test_runnums_with_tag(expname, tag='DARK'):
    """Print the result of ``runnums_with_tag(expname, tag)``."""
    print(runnums_with_tag(expname, tag))


  def test_run_table_data(expname):
    """Print ``run_table_data(expname)`` as indented JSON if it is truthy."""
    jo = run_table_data(expname)
    if jo: print(json.dumps(jo, indent=2))


  def test_runinfo_for_params(expname, params={"includeParams": "true"}):
    """Print the raw result of ``runinfo_for_params(expname, params)`` and, if truthy, the same as indented JSON."""
    jo = runinfo_for_params(expname, params)
    print('runinfo_for_params raw json:', jo)
    if jo: print(json.dumps(jo, indent=2))


  def test_run_table_data_resp(expname):
    """Send the 'run_table_data' GET request for ``expname`` directly with Kerberos headers and print the response object."""
    ws_url = "https://pswww.slac.stanford.edu/ws-kerb/lgbk/lgbk/%s/ws/run_table_data" % expname
    krbheaders = kerberos_headers()
    # cpo: add timeout here to debug intermittent hang in github actions
    r = requests.get(ws_url, headers=krbheaders, params={"tableName": "Scan Table"}, timeout=180)
    print(r)


  def test_run_files(expname, runnum):
    """Print ``run_files(expname, runnum)`` as indented JSON if it is truthy."""
    jo = run_files(expname, runnum)
    if jo: print(json.dumps(jo, indent=2))


  def test_runs_to_tags(expname):
    """Print ``runs_to_tags(expname)`` as indented JSON if it is truthy."""
    jo = runs_to_tags(expname)
    if jo: print(json.dumps(jo, indent=2))


  def test_tags_to_runs(expname):
    """Print ``tags_to_runs(expname)`` as indented JSON if it is truthy."""
    jo = tags_to_runs(expname)
    if jo: print(json.dumps(jo, indent=2))


  def test_tags_for_run(expname, runnum):
    """Print ``tags_for_run(expname, runnum)`` as indented JSON if it is truthy."""
    jo = tags_for_run(expname, runnum)
    if jo: print(json.dumps(jo, indent=2))


  def test_detnames(expname='xpplw2619', runnum=203):
    """Print the list returned by ``detnames(expname, runnum)``, one name per line."""
    lst = detnames(expname, runnum)
    print('detnames:\n ', '\n  '.join(lst))


  def test_is_lcls2(expname):
    """Print the result of ``is_lcls2(expname)``."""
    status = is_lcls2(expname)
    print('is_lcls2("%s"): %s' % (expname, str(status)))


if __name__ == "__main__":

    logging.basicConfig(format='[%(levelname).1s] L:%(lineno)03d %(name)s %(message)s', level=logging.DEBUG)

    tname = sys.argv[1] if len(sys.argv) > 1 else '0'
    print(50*'_', '\nTest %s' % tname)
    if   tname == '0': test_run_parameters('xcsdaq13', 200)
    elif tname == '1': test_all_runs_with_par_value()
    elif tname == '2': test_run_numbers('xpplw3319')
    elif tname == '3': test_run_numbers('xpptut15')
    elif tname == '4': test_run_numbers_at_location('xpplw3319', location='SLAC') #'NERSK'
    elif tname == '5': test_jsinfo_runs('xpptut15', location='SLAC')
    elif tname == '6': test_exp_tags('xpptut15') #xcsdaq13') #cxi78513')
    elif tname == '7': test_exprun_tags('tmox45719') #xcsdaq13')
    elif tname == '8': test_runnums_with_tag('xcsdaq13', tag='SCREENSHOT') # DARK')
    elif tname == '9': test_run_table_data(expname='xcsdaq13')
    elif tname =='10': test_run_table_data_resp(expname='xpplw3319')
    elif tname =='11': test_run_files('xcsdaq13', 200)
    elif tname =='12': test_runinfo_for_params('xcsdaq13', params={"includeParams": "true"})
    elif tname =='13': test_runinfo_for_params('xpplw3319', params={"includeParams": "true"})
    elif tname =='14': test_runinfo_for_params('xpptut15', params={"includeParams": "true"})
    elif tname =='15': test_runs_to_tags('xcsdaq13')
    elif tname =='16': test_tags_to_runs('xcsdaq13')
    elif tname =='17': test_tags_for_run('tmolw8819', 111)
    elif tname =='18': test_is_lcls2('xpplw3319')
    elif tname =='19': test_is_lcls2('tmolw8819')
    elif tname =='20': test_detnames(expname='xpplw2619', runnum=203)
    elif tname =='21': test_detnames(expname='tmolv3919', runnum=11)
    elif tname =='22': test_run_parameters('tmolv3919', 11)
    else: print('test %s is not implemented' % tname)

    sys.exit('End of Test %s' % tname)

# EOF
