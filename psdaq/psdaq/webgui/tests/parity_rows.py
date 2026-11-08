"""Which headless-browser test proves which parity row of the main window (mapping.d/mainwindow.json).

conftest.py records each listed row as a junit `parity` property of the test (record_property), and
check_parity counts a row as mapped only if the mapped test passed AND carries that property.
test_check_parity.test_mainwindow_fragment_matches_rows checks that mapping.d/mainwindow.json says
exactly this.  (The config editor's rows: ROWS in test_configeditor_ui.py, mapping.d/configeditor.json.)
"""

ROWS = {
    'test_webgui_ui': {
        'test_full_cycle': ['CGWMainControl.box_state', 'CGWMainPartition.but_select', 'QWPopupTableCheck.but_apply'],
        'test_record_toggle': ['CGWMainControl.but_record'],
        'test_partition_columns_apply': ['CGWMainPartition.w_select.sel', 'CGWMainPartition.w_select.monitor',
                                         'CGWMainPartition.w_select.grp',
                                         'CGWPartitionTable.set_readout_group_number@1'],
        'test_collection_and_show_window': ['CGWMainPartition.but_show'],
        'test_refresh_buttons': ['CGWMainControl.but_transition', 'CGWMainControl.but_ctrls'],
    },
    'test_webgui_parity_ui': {
        'test_select_id_collapses_and_expands_detector': ['CGWMainPartition.w_select.id'],
        'test_show_id_collapses_and_expands_detector': ['CGWMainPartition.w_show.id'],
        'test_partition_display_cells_shown_not_editable': [
            'CGWMainPartition.w_select.level_pid_host', 'CGWMainPartition.w_show.sel',
            'CGWMainPartition.w_show.grp', 'CGWMainPartition.w_show.level_pid_host',
            'CGWMainPartition.w_show.monitor'],
        'test_collection_cells_shown_not_editable': ['CGWPanelList.fill_list_model@1'],
        'test_logger_text_shown_read_only': ['QWLoggerStd.edi_txt', 'QWLoggerError.edi_err'],
        'test_box_state_ignores_arrow_keys_and_wheel': ['CGWMainControl.box_state.keyPressEvent',
                                                         'CGWMainControl.box_state.wheelEvent'],
        'test_alt_a_applies_select_window': ['QWPopupTableCheck.but_apply.mnemonic'],
        'test_tab_bar_user_and_expert': ['CGWMainTabs.tab_bar.user', 'CGWMainTabs.tab_bar.expert'],
        'test_user_tab_play_stop_record': ['CGWMainTabUser.but_play', 'CGWMainTabUser.but_stop',
                                           'CGWMainTabUser.but_record'],
        'test_popup_edit_text_mnemonics': ['QWPopupEditText.but_cancel.mnemonic', 'QWPopupEditText.but_apply.mnemonic'],
        'test_config_tree_key_and_index_cells_not_editable': ['CGWConfigEditorTree.tree_model_from_dict@1',
                                                              'CGWConfigEditorTree.tree_model_from_dict@2'],
    },
}

# CSS selector of the web element for a row, when it is not [data-parity~="<row id>"]
WEB = {
    'QWPopupEditText.but_cancel.mnemonic': '[data-parity~="QWPopupEditText.but_cancel"][data-accesskey="c"]',
    'QWPopupEditText.but_apply.mnemonic': '[data-parity~="QWPopupEditText.but_apply"][data-accesskey="a"]',
}


def fragment():
    """mapping.d/mainwindow.json as ROWS says it."""
    out = {}
    for mod, tests in ROWS.items():
        for t, rids in tests.items():
            for rid in rids:
                out[rid] = {'web': WEB.get(rid, '[data-parity~="%s"]' % rid), 'test': '%s.py::%s[chromium]' % (mod, t)}
    return out


if __name__ == '__main__':          # regenerate the fragment: python parity_rows.py > ../parity/mapping.d/mainwindow.json
    import json
    print(json.dumps(fragment(), indent=1, sort_keys=True))
