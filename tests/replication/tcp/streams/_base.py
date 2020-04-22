# -*- coding: utf-8 -*-
# Copyright 2019 New Vector Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from mock import Mock

from synapse.app.generic_worker import GenericWorkerServer
from synapse.replication.tcp.client import ReplicationDataHandler
from synapse.replication.tcp.handler import ReplicationCommandHandler
from synapse.replication.tcp.protocol import ClientReplicationStreamProtocol
from synapse.replication.tcp.resource import ReplicationStreamProtocolFactory

from tests import unittest
from tests.server import FakeTransport


class BaseStreamTestCase(unittest.HomeserverTestCase):
    """Base class for tests of the replication streams"""

    def prepare(self, reactor, clock, hs):
        # build a replication server
        server_factory = ReplicationStreamProtocolFactory(hs)
        self.streamer = hs.get_replication_streamer()
        self.server = server_factory.buildProtocol(None)

        # Make a new HomeServer object for the worker
        config = self.default_config()
        config["worker_app"] = "synapse.app.generic_worker"

        self.worker_hs = self.setup_test_homeserver(
            http_client=None,
            homeserverToUse=GenericWorkerServer,
            config=config,
            reactor=self.reactor,
        )

        self.test_handler = Mock(
            wraps=TestReplicationDataHandler(self.worker_hs.get_datastore())
        )
        self.worker_hs.replication_data_handler = self.test_handler

        # Since we use sqlite in memory databases we need to make sure the
        # databases objects are the same.
        self.worker_hs.get_datastore().db = hs.get_datastore().db

        repl_handler = ReplicationCommandHandler(self.worker_hs)

        self.client = ClientReplicationStreamProtocol(
            hs, "client", "test", clock, repl_handler,
        )

        self._client_transport = None
        self._server_transport = None

    def reconnect(self):
        if self._client_transport:
            self.client.close()

        if self._server_transport:
            self.server.close()

        self._client_transport = FakeTransport(self.server, self.reactor)
        self.client.makeConnection(self._client_transport)

        self._server_transport = FakeTransport(self.client, self.reactor)
        self.server.makeConnection(self._server_transport)

    def disconnect(self):
        if self._client_transport:
            self._client_transport = None
            self.client.close()

        if self._server_transport:
            self._server_transport = None
            self.server.close()

    def replicate(self):
        """Tell the master side of replication that something has happened, and then
        wait for the replication to occur.
        """
        self.streamer.on_notifier_poke()
        self.pump(0.1)


class TestReplicationDataHandler(ReplicationDataHandler):
    """Drop-in for ReplicationDataHandler which just collects RDATA rows"""

    def __init__(self, hs):
        super().__init__(hs)
        self.streams = set()
        self._received_rdata_rows = []

    async def on_rdata(self, stream_name, token, rows):
        await super().on_rdata(stream_name, token, rows)
        for r in rows:
            self._received_rdata_rows.append((stream_name, token, r))
