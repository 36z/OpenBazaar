import zmq
c = zmq.Context()
s = c.socket(zmq.REQ)
s.connect("tcp://localhost:5558")
s.send("genjix")
key = s.recv()
if key == "__NONE__":
    print "Invalid nick"
else:
    print key.encode("hex")

