"""Define `EventBuilderManager`, which yields event and step batches built from one smalldata packet."""
from psana.eventbuilder import EventBuilder
from psana.psexp.packet_footer import PacketFooter

from .callback_batch import CallbackBatchBuilder
from .run import RunSmallData


class EventBuilderManager(object):
    """Build batches of events and steps from one packet of per-file smalldata views.

    The constructor splits `view` into per-file views with `PacketFooter`, creates an
    `EventBuilder` (C extension `psana.eventbuilder`) with the filter timestamps,
    integrating-detector stream id and batch size from `dsparms`, and wraps it in a `RunSmallData`
    and a `CallbackBatchBuilder`, which are used when `dsparms.smd_callback` is set. Proxy events
    are enabled in the builder when a smalldata callback or `dsparms.intg_det` is set.
    """
    def __init__(self, view, configs, dsparms, callback_run_state=None):
        self.configs = configs
        self.dsparms = dsparms
        self.n_files = len(self.configs)

        pf = PacketFooter(view=view)
        views = pf.split_packets()
        use_proxy_events = bool(dsparms.smd_callback or getattr(dsparms, "intg_det", ""))
        self.eb = EventBuilder(views,
                               self.configs,
                               filter_timestamps=dsparms.timestamps,
                               intg_stream_id=dsparms.intg_stream_id,
                               batch_size=dsparms.batch_size,
                               use_proxy_events=use_proxy_events)
        self.run_smd = RunSmallData(
            self.eb,
            configs,
            dsparms,
            callback_run_state=callback_run_state,
        )  # only used by smalldata callback
        self.callback_batch_builder = CallbackBatchBuilder(
            self.eb,
            self.run_smd,
            dsparms.smd_callback,
            batch_size=dsparms.batch_size,
            respect_batch_size=True,
        )

    def batches(self):
        """Yield `(batch_dict, step_dict)` tuples until the event builder is exhausted.

        Without a smalldata callback (`dsparms.smd_callback == 0`) each tuple comes from
        `EventBuilder.build()`, and the loop ends when a build gives no events and no steps; otherwise
        the tuples come from `CallbackBatchBuilder.next_batch()` until it returns None. The batch
        contents are produced by the event builder extension; not visible here.
        """
        while True:
            # This eiter calls user-defined smalldata callback, which loops
            # over smd events or skips (faster). To enable detector inteface
            # for smd events, evt.complete() (slow) is called.
            # Note: use _smd_callback for checking if user set any callback
            # through DataSource.
            if self.dsparms.smd_callback == 0:
                batch_dict, step_dict = self.eb.build()
                if self.eb.nevents == 0 and self.eb.nsteps == 0:
                    break
            else:
                callback_batch = self.callback_batch_builder.next_batch()
                if callback_batch is None:
                    break
                batch_dict, step_dict = callback_batch

            yield batch_dict, step_dict
