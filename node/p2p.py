import json
import logging
from collections import defaultdict
import traceback

from zmq.eventloop import ioloop
import zmq
from multiprocessing import Process, Queue
from threading import Thread
ioloop.install()

from protocol import goodbye
import network_util
import hashlib
import routingtable
import datastore
from urlparse import urlparse

# Connection to one peer
class PeerConnection(object):
    def __init__(self, transport, address, guid):
        # timeout in seconds
        self._timeout = 10
        self._transport = transport
        self._address = address
        self._guid = guid
        self._log = logging.getLogger(self.__class__.__name__)

    def create_socket(self):
        self._ctx = zmq.Context()
        self._socket = self._ctx.socket(zmq.REQ)
        self._socket.setsockopt(zmq.LINGER, 0)
        self._socket.connect(self._address)

    def cleanup_socket(self):
        self._socket.close()

    def send(self, data):
        self.send_raw(json.dumps(data))

    def send_raw(self, serialized, callback=None):
        Thread(target=self._send_raw, args=(serialized,callback)).start()
        pass

    def _send_raw(self, serialized, callback=None):

        # pyzmq sockets are not threadsafe,
        # they have to run in a separate process
        queue = Queue()
        # queue element is false if something went wrong and the peer
        # has to be removed
        p = Process(target=self._send_raw_process, args=(serialized, queue, callback))
        p.start()
        if not queue.get():
            self._log.info("Peer %s timed out." % self._address)
            self._transport.remove_peer(self._address)
        p.join()

    def _send_raw_process(self, serialized, queue, callback=None):

        self.create_socket()
        self._socket.send(serialized)

        poller = zmq.Poller()
        poller.register(self._socket, zmq.POLLIN)
        if poller.poll(self._timeout * 5000):
            msg = self._socket.recv()
            self.on_message(msg, callback)
            self.cleanup_socket()
            queue.put(True)

        else:
            self.cleanup_socket()
            queue.put(False)


    def on_message(self, msg, callback=None):
        if callback:
          callback(msg)
        self._log.info("message received! %s" % msg)


# Transport layer manages a list of peers
class TransportLayer(object):
    def __init__(self, my_ip, my_port):
        self._peers = {}
        self._callbacks = defaultdict(list)
        self._port = my_port
        self._ip = my_ip
        self._uri = 'tcp://%s:%s' % (self._ip, self._port)
        self._guid = self.generate_guid().encode('hex')

        # Routing table
        self._routingTable = routingtable.OptimizedTreeRoutingTable(self._guid)
        self._dataStore = datastore.MongoDataStore()
        self._knownNodes = []


        self._log = logging.getLogger(self.__class__.__name__)
        # signal.signal(signal.SIGTERM, lambda x, y: self.broadcast_goodbye())

    def add_callback(self, section, callback):
        self._callbacks[section].append(callback)

    def generate_guid(self):
      guid = hashlib.sha1()
      guid.update("%s:%s" % (self._ip, self._port))
      return guid.digest()

    def trigger_callbacks(self, section, *data):
        for cb in self._callbacks[section]:
            cb(*data)
        if not section == 'all':
            for cb in self._callbacks['all']:
                cb(*data)

    def get_profile(self):
        return {'type': 'hello_request', 'uri': self._uri}

    def join_network(self, seed_uri):

        self.listen() # Turn on zmq socket

        if seed_uri:
            self.init_peer({'uri': seed_uri})

            # Get Seed info
            node_ip = urlparse(seed_uri).hostname
            node_port = urlparse(seed_uri).port
            node_guid = hashlib.new('sha1')
            node_guid.update("%s:%s" % (node_ip, node_port))
            node_guid = node_guid.digest().encode('hex')


            if (node_ip, node_port, node_guid) not in self._knownNodes:
                self._knownNodes.append((node_ip, node_port, node_guid))
                # Need to persist this in MongoDB
                # Used when starting server back up

            # Add to routing table
            #aContact = Contact(node_guid, uri)
            #self._routingTable.addContact(aContact)
            seed_node = PeerConnection(self, seed_uri, node_guid)
            self._routingTable.addContact(seed_node)


        # Send findNode call to other nodes to let them know we're online
        def joinedNetwork(msg):

            if msg != None:
              msg = json.loads(msg)
              if msg['type'] == 'ok':
                print 'Found myself: %s' % self._guid

        self._iterativeFind(self._guid, self._knownNodes, 'findNode', joinedNetwork)

        # Referesh the k-buckets periodically


    def listen(self):
        t = Thread(target=self._listen)
        t.setDaemon(True)
        t.start()

    def _listen(self):
        self._log.info("init server %s %s" % (self._ip, self._port))
        self._ctx = zmq.Context()
        self._socket = self._ctx.socket(zmq.REP)

        if network_util.is_loopback_addr(self._ip):
            # we are in local test mode so bind that socket on the
            # specified IP
            self._socket.bind(self._uri)
        else:
            try:
              self._socket.bind('tcp://*:%s' % self._port)
            except:
              pass


        while True:
            message = self._socket.recv()
            self.on_raw_message(message)
            self._socket.send(json.dumps({'type': "ok"}))

    def closed(self, *args):
        self._log.info("client left")

    def _init_peer(self, msg):
        uri = msg['uri']

        if uri not in self._peers:
            self._peers[uri] = PeerConnection(self, uri)

    def remove_peer(self, uri):
        self._log.info("Removing peer %s", uri)
        try:
            del self._peers[uri]
            msg = {
                'type': 'peer_remove',
                'uri': uri
            }
            self.trigger_callbacks(msg['type'], msg)

        except KeyError:
            self._log.info("Peer %s was already removed", uri)

    def send(self, data, send_to=None):

        # self._log.info("Data sent to p2p: %s" % data);

        # directed message
        if send_to:
            for peer in self._peers.values():
                if peer._pub == send_to:
                    if peer.send(data):
                        self._log.info('Success')
                    else:
                        self._log.info('Failed')

                    return

            self._log.info("Peer not found! %s %s",
                           send_to, self._myself.get_pubkey())
            return

        # broadcast
        for peer in self._peers.values():
            try:
                if peer._pub:
                    peer.send(data)
                else:
                    serialized = json.dumps(data)
                    peer.send_raw(serialized)
            except:
                self._log.info("Error sending over peer!")
                traceback.print_exc()

    def broadcast_goodbye(self):
        self._log.info("Broadcast goodbye")
        msg = goodbye({'uri': self._uri})
        self.send(msg)

    def on_message(self, msg):
        # here goes the application callbacks
        # we get a "clean" msg which is a dict holding whatever
        self._log.info("Data received: %s" % msg)
        self.trigger_callbacks(msg.get('type'), msg)

    def on_raw_message(self, serialized):
        self._log.info("connected " + str(len(serialized)))
        try:
            msg = json.loads(serialized[0])
        except:
            self._log.info("incorrect msg! " + serialized)
            return

        msg_type = msg.get('type')
        if msg_type == 'hello_request' and msg.get('uri'):
            self.init_peer(msg)
        else:
            self.on_message(msg)

    def valid_peer_uri(self, uri):
        try:
            [self_protocol, self_addr, self_port] = \
                network_util.uri_parts(self._uri)
            [other_protocol, other_addr, other_port] = \
                network_util.uri_parts(uri)
        except RuntimeError:
            return False

        if not network_util.is_valid_protocol(other_protocol)  \
                or not network_util.is_valid_port(other_port):
            return False

        if network_util.is_private_ip_address(self_addr):
            if not network_util.is_private_ip_address(other_addr):
                self._log.warning(('Trying to connect to external '
                                   'network with a private ip address.'))
        else:
            if network_util.is_private_ip_address(other_addr):
                return False

        return True
