import logging
import asyncio
import sys
import inspect
import signal
import binascii
from os import devnull
from contextlib import suppress
from re import search

from .listeners import Listeners
from .protocol import PROTO, ProtocolHandler

LOGGER = logging.getLogger(__name__)


class TCPFlowError(Exception):
    def __init__(self, ex=None):
        super().__init__()
        self.ex = ex

    def __str__(self):
        if self.ex is not None:
            return str(self.ex).strip()
        return TCPFlowError.__name__


class TCPFlowProtocol(asyncio.SubprocessProtocol):
    def __init__(self, loop, name):
        self.stopped = False
        self.error_data = str()
        self._loop = loop
        self._name = name
        self._future = self._loop.create_future()

    def pipe_data_received(self, fd, data):
        if fd == 1:
            self._future.set_result(data)
            self._future = self._loop.create_future()
        elif fd == 2:
            for e in data.decode("utf8").splitlines():
                self.error_data += e + "\n"
            # program prints status stuff into stderr so we have to ignore it
            for status in "listening", "reportfilename":
                if status in self.error_data or len(self.error_data) <= 2:
                    self.error_data = str()
                    break

    async def yielder(self):
        """
        Yielding async generator that turns tcpflow output into a single string
        of hex encoded bytes. This function is operable only when tcpflow is run
        with and only -B and -C arguments.
        """
        while not self.stopped:
            try:
                data = await self._future
                for l in data.split(b"\n"):
                    packet = binascii.hexlify(l).decode("ascii")
                    if packet != "":
                        yield packet
            except (IndexError, AttributeError):
                pass
            except asyncio.CancelledError:
                break

    def pipe_connection_lost(self, _fd, _exc):
        self.stopped = True
        self._future.cancel()

    def process_exited(self):
        LOGGER.debug("%s TCPFlow instance exited.", self._name.capitalize())
        self.stopped = True
        self._future.cancel()


class Mousapi:

    tasklist = list()

    def __init__(self):
        if sys.platform != "win32":
            self.loop = asyncio.new_event_loop()
        else:
            self.loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(self.loop)

        self.game_transport = None
        self.game_protocol = None
        self.community_transport = None
        self.community_protocol = None
        self.retcodes = None
        self.community = ["tcp and src 164.132.202.12 and greater 69"]
        # game ports so far 44440, 44444, 6112, 3724, 5555
        self.game = [
            "tcp and port 6112 or port 44440 or port 44444 or port 3724"
            " or port 5555 and greater 69 and inbound"
        ]
        self.event = asyncio.Event()
        self.listener = Listeners()
        self.protohandler = ProtocolHandler()
        # self.barrier = mp.Barrier(2)
        # barrier = None
        # self.thread = mp.Process(daemon=True, target=self._loop)
        # self.thread.start()
        # self.barrier.wait()
        # self.thread.join()
        # self.run()

    # def _loop(self):
    # """Actual thread"""

    # try:
    # print("before")
    # self.barrier.wait()
    # print("after")
    # self.run()
    # except Exception:
    # sys.exit(1)

    def add_listener(self, event, data):
        self.listener.add(event, data)

    async def _init_protocol_and_transport(self):
        args = list()
        args.append("tcpflow")
        args.append("-BC")
        args.append("-X" + devnull)

        for i in "community", "game":
            transport, protocol = await self.loop.subprocess_exec(
                lambda x=i: TCPFlowProtocol(self.loop, x),
                *args + getattr(self, i),
                stdout=asyncio.subprocess.PIPE,
                stdin=None,
                stderr=asyncio.subprocess.PIPE
            )
            setattr(self, i + "_transport", transport)
            setattr(self, i + "_protocol", protocol)
        self.event.set()

    async def _handle_community_server_data(self):
        await self.event.wait()
        async for line in self.community_protocol.yielder():
            event = line[12:18]
            LOGGER.debug("What's the community event: %s", event)
            if event in self.protohandler:
                self.listener.enqueue(PROTO[event], self.protohandler(event, line))
                self.listener.process()
        if self.community_protocol.error_data:
            self.game_transport.close()
            raise TCPFlowError(self.community_protocol.error_data)

    async def _handle_game_server_data(self):
        await self.event.wait()
        async for line in self.game_protocol.yielder():
            event = line[:8]
            LOGGER.debug("What's the game event: %s", event)
            if event in self.protohandler:
                self.listener.enqueue(PROTO[event], self.protohandler(event, line))
                self.listener.process()
        if self.game_protocol.error_data:
            self.community_transport.close()
            raise TCPFlowError(self.game_protocol.error_data)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, _exc_value, _traceback):
        if exc_type is not RuntimeError:
            self.gracefull_close()
        else:
            self.loop.close()

    @property
    def global_stop(self):
        return self.community_protocol.stopped or self.game_protocol.stopped

    @global_stop.setter
    def global_stop(self, value):
        self.community_protocol.stopped = self.game_protocol.stopped = value

    def _append_tasks(self):
        fnames_fobjs = inspect.getmembers(self, predicate=inspect.iscoroutinefunction)

        for fname, fobj in fnames_fobjs:
            Mousapi.tasklist.append((fname, fobj))

    def listen(self):
        if not len(self.listener):
            raise RuntimeError("I got nothing to listen to!")

        def handler(_signum, _frame):
            nonlocal self
            self.global_stop = True
            LOGGER.info("User exited with SIGQUIT")

        signal.signal(signal.SIGQUIT, handler)
        self._append_tasks()

        LOGGER.debug("Current coroutines: %s", self.tasklist)

        self.retcodes, _pending = self.loop.run_until_complete(
            asyncio.wait([fobj() for _fname, fobj in Mousapi.tasklist])
        )
        # return_when=asyncio.ALL_COMPLETED))

    def gracefull_close(self):
        """Close all pending tasks and exit"""

        def print_coro(coro):
            return search(r"coro=<\s*(.+?)\s*>", str(coro)).group(1)

        self.global_stop = True

        with suppress(ProcessLookupError):
            self.community_transport.terminate()
            self.game_transport.terminate()

        pending = asyncio.Task.all_tasks()
        errors = list()
        for task in pending:
            task.cancel()
            # # Now we should await task to execute it's cancellation.
            # # Cancelled task raises asyncio.CancelledError that we can suppress:
            with suppress(asyncio.CancelledError):
                try:
                    self.loop.run_until_complete(task)
                except TCPFlowError:
                    errors.append((print_coro(task), task.exception()))

        self.loop.close()
        if self.retcodes is not None:
            for coro, ex in errors:
                LOGGER.error("\n%s returned: %s", coro, ex)

        LOGGER.info("See ya araound")
        if errors:
            return 1
        return 0
