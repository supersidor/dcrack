#!/usr/bin/python

import sys
import os
import subprocess
import random
import time
import sqlite3
import threading
import hashlib
import gzip
import json
import datetime
import re
import threading
import socket

if sys.version_info[0] >= 3:
	from socketserver import ThreadingTCPServer
	from urllib.request import urlopen, URLError
	from urllib.parse import urlparse, parse_qs
	from http.client import HTTPConnection
	from http.server import SimpleHTTPRequestHandler
else:
	from SocketServer import ThreadingTCPServer
	from urllib2 import urlopen, URLError
	from urlparse import urlparse, parse_qs
	from httplib import HTTPConnection
	from SimpleHTTPServer import SimpleHTTPRequestHandler

	bytes = lambda a, b : a

port = 1337
url = None
cid = None
tls = threading.local()
nets = {}
cracker = None
#splitcount=30000
splitcount=3000000
dictdir = "dict"

class ServerHandler(SimpleHTTPRequestHandler):
	def do_GET(s):
		result = s.do_req(s.path)

		if not result:
			return

		s.send_response(200)
		s.send_header("Content-type", "text/plain")
		s.end_headers()
		s.wfile.write(bytes(result, "UTF-8"))

	def do_POST(s):
		if ("dict" in s.path):
			s.do_upload_dict()

		if ("cap" in s.path):
			s.do_upload_cap()

		s.send_response(200)
		s.send_header("Content-type", "text/plain")
		s.end_headers()
		s.wfile.write(bytes("OK", "UTF-8"))
	
	def do_upload_dict(s):
		con = get_con()
		cl = int(s.headers['Content-Length'])

		tempfile = "dcrack-dict.txt"
		try:
    			os.remove(tempfile)
		except OSError:
    			pass
		o = open(tempfile, "wb")
		count = 0;
		while count<cl:
			toread = 10000
			if count+toread>cl:
				toread = cl-count
			data = s.rfile.read(toread)
			o.write(data)
			count=count+len(data)
		o.close()


		if not os.path.exists(dictdir):
    			os.makedirs(dictdir)
		else:
		   filelist = [ f for f in os.listdir(dictdir)]
		   for f in filelist:
    			os.remove(dictdir+"/"+f)

		lines = 0;
		part=1
		
		arch = create_dictpart(part)
		with open(tempfile) as fdata:
	    		for line in fdata:
				arch.write(line)
				lines = lines + 1
				if lines>splitcount:
					arch.close()
					lines = 0
					part = part + 1
					arch = create_dictpart(part)

		arch.close()			  
	def do_upload_cap(s):
		cl = int(s.headers['Content-Length'])
		f = open("dcrack.cap.tmp.gz", "wb")
		f.write(s.rfile.read(cl))
		f.close()

		decompress("dcrack.cap.tmp.gz","dcrack.cap.tmp")
		os.rename("dcrack.cap.tmp.gz", "dcrack.cap.gz")
		os.rename("dcrack.cap.tmp", "dcrack.cap")

	def do_req(s, path):
		con = get_con()

		c = con.cursor()

		c.execute("""DELETE from clients where 
			    (strftime('%s', datetime()) - strftime('%s', last))
			    > 300""")

		con.commit()

		if ("ping" in path):
			return s.do_ping(path)

		if ("getwork" in path):
			return s.do_getwork(path)


		if ("dict" in path):
			return s.get_dict(path)

		if ("net" in path and "/crack" in path):
			return s.do_crack(path)

		if ("net" in path and "result" in path):
			return s.do_result(path)

		if ("cap" in path):
			return s.get_cap(path)

		if ("status" in path):
			return s.get_status()

		if ("remove" in path):
			return s.remove(path)

		return "error"

	def remove(s, path):
		con = get_con()

		p = path.split("/")
		n = p[4].upper()

		c = con.cursor()
		c.execute("DELETE from nets where bssid = ?", (n,))
		con.commit()

		c.execute("DELETE from work where net = ?", (n,))
		con.commit()
		
		return "OK"

	def get_status(s):
		con = get_con()

		c = con.cursor()
		c.execute("SELECT * from clients")
	
		clients = []
		for r in c.fetchall():
			client = {}
			client['speed']=r['speed']
			client['name']=r['name']			
			clients.append(client)

		nets = []

		c.execute("SELECT * from nets")

		for r in c.fetchall():
			n = { "bssid" : r['bssid'] }
			if r['pass']:
				n["pass"] = r['pass']

			if r['state'] != 2:
				cur = con.cursor()
				cur.execute("""SELECT * from work WHERE net = ? """,(n['bssid'],))
				total = 0
				finished = 0
				inprogress = 0
				for row in cur.fetchall():
					total = total + 1
					if row['state']==2:
						finished+=1
					elif row['state']==1:
						inprogress+=1
				n['parts']=total
				n['finished']=finished
				n['inprogress']=inprogress
	
				"""n["tot"] = dic["lines"]

				did = 0
				cur = con.cursor()
				cur.execute(SELECT * from work where net = ?
						and dict = ? and state = 2,
						(n['bssid'], dic['id']))
				for row in cur.fetchall():
					did += row['end'] - row['start']

				n["did"] = did
			"""
			nets.append(n)
		d = { "clients" : clients, "nets" : nets }

		return json.dumps(d)

	def do_result_pass(s, net, pw):
		con = get_con()

		pf = "dcrack-pass.txt"

		f = open(pf, "w")
		f.write(pw)
		f.write("\n")
		f.close()

		cmd = ["aircrack-ng", "-w", pf, "-b", net, "-q", "dcrack.cap"]
		p = subprocess.Popen(cmd, stdout=subprocess.PIPE, \
			stdin=subprocess.PIPE)

		res = p.communicate()[0]
		res = str(res)

		os.remove(pf)

		if not "KEY FOUND" in res:
			return "error"

		s.net_done(net)

		c = con.cursor()
		c.execute("UPDATE nets set pass = ? where bssid = ?", \
			(pw, net))

		con.commit()
		c.execute("UPDATE work set state = 2 where net = ?", \
			(net,))

		con.commit()

		return "OK"

	def net_done(s, net):
		con = get_con()

		c = con.cursor()
		c.execute("UPDATE nets set state = 2 where bssid = ?",
			(net,))

		c.execute("DELETE from work where net = ?", (net,))
		con.commit()

	def do_result(s, path):
		con = get_con()

		p = path.split("/")
		n = p[4].upper()

		x  = urlparse(path)
		qs = parse_qs(x.query)

		if "pass" in qs:
			return s.do_result_pass(n, qs['pass'][0])

		part = qs['part'][0]
		print n
		print part
		c = con.cursor()
		c.execute("SELECT * from nets where bssid = ?", (n,))
		r = c.fetchone()
		if r and r['state'] == 2:
			return "Already done"

		c.execute("""UPDATE work set state = 2 where 
			net = ? and part = ?""",
			(n, part))

		con.commit()

		return "OK"

	def get_cap(s, path):
		return s.serve_file("dcrack.cap.gz")

	def get_dict(s, path):
		p = path.split("/")
		n = p[4]

		fn = dictdir+"/%s.txt.gz" % n

		return s.serve_file(fn)

	def serve_file(s, fn):
		s.send_response(200)
		s.send_header("Content-type", "application/x-gzip")
		s.end_headers()

		# XXX openat
		f = open(fn, "rb")
		s.wfile.write(f.read())
		f.close()

		return None

	def do_crack(s, path):
		con = get_con()

		p = path.split("/")

		n = p[4].upper()

		c = con.cursor()
		c.execute("INSERT into nets values (?, NULL, 1)", (n,))
		con.commit()


		if not os.path.exists(dictdir):
    			os.makedirs(dictdir)
		filelist = [ f for f in os.listdir(dictdir)]
		part = 1
		for f in filelist:
			c.execute("INSERT into work values (?, ?,NULL,0)", (n,part,))
			part = part + 1
		con.commit()


		return "OK"


	def do_ping(s, path):
		con = get_con()

		p = path.split("/")

		cid = p[4]

		x  = urlparse(path)
		qs = parse_qs(x.query)
                print qs
		speed = qs['speed'][0]
		name = qs['name'][0]

		c = con.cursor()
		c.execute("SELECT * from clients where id = ?", (cid,))
		r = c.fetchall()
		if (not r):
			c.execute("INSERT into clients values (?, ?,?, datetime())",
				  (cid, int(speed),name))
		else:
			c.execute("""UPDATE clients set speed = ?, 
					last = datetime() where id = ?""",
					(int(speed), cid))

		con.commit()

		return "60"

	def try_network(s, net, d):
		con = get_con()

		c = con.cursor()
		c.execute("""SELECT * from work where net = ? and dict = ?
				order by start""", (net['bssid'], d['id']))

		r = c.fetchall()

		s     = 5000000
		i     = 0
		found = False

		for row in r:
			if found:
				if i + s > row['start']:
					s = row['start'] - i
				break

			if (i >= row['start'] and i <= row['end']):
				i = row['end']
			else:
				found = True

		if i + s > d['lines']:
			s = d['lines'] - i

		if s == 0:
			return None

		c.execute("INSERT into work values (NULL, ?, ?, ?, ?, datetime(), 1)",
			(net['bssid'], d['id'], i, i + s))

		con.commit()

		crack = { "net"   : net['bssid'], \
			  "dict"  : d['id'], \
			  "start" : i, \
			  "end"   : i + s }

		j = json.dumps(crack)

		return j

	def do_getwork(s, path):
		con = get_con()

		c = con.cursor()
		c.execute("""UPDATE work SET state=0 WHERE 
			    ((strftime('%s', datetime()) - strftime('%s', requested))
			    > 3600) and state = 1""")


		c.execute("select * from work where state = 0  limit 1")
		print "get work"
		res = c.fetchone()
		if res:
			crack = {"net" : res['net'], 'part' : res['part']}
			print crack
			c.execute("UPDATE work SET state=1,requested=datetime() WHERE net=? AND part=?",(res['net'],res['part']))
			con.commit()
			return json.dumps(crack)
		res = { "interval" : "60" }

		return json.dumps(res)
		

		"""c.execute(DELETE from work where 
			    ((strftime('%s', datetime()) - strftime('%s', last))
			    > 3600) and state = 1)

		con.commit()

		c.execute("SELECT * from dict where current = 1")
		d = c.fetchone()

		c.execute("SELECT * from nets where state = 1")
		r = c.fetchall()

		for row in r:
			res = s.try_network(row, d)
			if res:
				return res

		# try some old stuff
		c.execute(select * from work where state = 1 
			order by last limit 1)

		res = c.fetchone()

		if res:
			c.execute("DELETE from work where id = ?", (res['id'],))
			for row in r:
				res = s.try_network(row, d)
				if res:
					return res
		"""


def create_db():
	con = get_con()

	c = con.cursor()
	c.execute("""create table clients (id varchar(255),
			speed integer, name varchar(255), last datetime)""")

	c.execute("""create table nets (bssid varchar(255) primary key, pass varchar(255),
			state integer)""")

#	c.execute("""create table work (id integer primary key,
#		net varchar(255), dict varchar(255),
#		start integer, end integer, last datetime, state integer)""")

	c.execute("""create table work (net varchar(255),part integer,requested datetime, state integer)""")

def connect_db():
	con = sqlite3.connect('dcrack.db')
	con.row_factory = sqlite3.Row

	return con

def get_con():
	global tls

	try:
		return tls.con
	except:
		tls.con = connect_db()
		return tls.con

def init_db():
	con = get_con()
	c = con.cursor()

	try:
		c.execute("SELECT * from clients")
	except:
		create_db()

class myClass():
    def __init__(self,httpd):
	self.httpd = httpd;
    def shutdown(self):
	httpd.shutdown()
httpd = None
def server():
	init_db()
	
	server_class = ThreadingTCPServer
	server_class.allow_reuse_address = True
	global httpd 
	httpd = server_class(('0.0.0.0', port), ServerHandler)

	import signal
	import sys
	def signal_handler(signal, frame):
		print('Ctrl+C pressed!')
		m = myClass(httpd)
		thread = threading.Thread(target = m.shutdown)
		thread.start()
	signal.signal(signal.SIGINT, signal_handler)
	print "Starting server"
        httpd.serve_forever()
	httpd.server_close()
def usage():
	print("""dcrack v0.3

	Usage: dcrack.py [MODE]
	server                        Runs coordinator
	client  <server addr>          Runs cracker
	clientp <server addr>          Runs pyrit cracker
	cmd    <server addr> [CMD]    Sends a command to server

		[CMD] can be:
			dict   <file>
			cap    <file>
			crack  <bssid>
			remove <bssid>
			status""")
	exit(1)

def get_speed(pyrit):
	print("Getting speed")
	if not pyrit:
		p = subprocess.Popen(["aircrack-ng", "-S"], stdout=subprocess.PIPE)
		speed = p.stdout.readline()
		speed = speed.split()
		speed = speed[len(speed) - 2]
		return int(speed)
	else:
		p = subprocess.Popen(["pyrit", "benchmark"], stdout=subprocess.PIPE)	
		res = p.communicate()[0]
		res = str(res)
		print res
		m = re.search("Computed (\d+[.]\d+) PMKs/s total",res);
		speed = m.group(1)
		speed = int(float(speed))
		print "myspeed",speed
		return speed
def get_cid():
	return random.getrandbits(64)

def do_ping(speed):
	global url, cid

	u = url + "client/" + str(cid) + "/ping?speed=" + str(speed)+"&name="+socket.gethostname()
	stuff = urlopen(u).read()
	interval = int(stuff)

	return interval

def pinger(speed):
	while True:
		interval = try_ping(speed)
		time.sleep(interval)

def try_ping(speed):
	while True:
		try:
			return do_ping(speed)
		except URLError:
			print("Conn refused (pinger)")
			time.sleep(60)

def get_work(pyrit):
	global url, cid, cracker,nets

	u = url + "client/" + str(cid) + "/getwork"
	stuff = urlopen(u).read()
	stuff = stuff.decode("utf-8")

	crack = json.loads(stuff)
	print(crack)
	if "interval" in crack:
		print("Waiting")
		return int(crack['interval'])

	wl  = setup_dict(crack)
	cap = get_cap(crack)
	print wl
	print cap
	if crack['net'] not in nets:
	     print("Can't find net %s" % crack['net'])
	     u = "%snet/%s/result?part=%s" % \
		   	(url, crack['net'], crack['part'])

	     stuff = urlopen(u).read()
	     print stuff
	
	print("Cracking")

	if not pyrit:
		cmd = ["aircrack-ng", "-w", wl, "-b", crack['net'], "-q", cap]

		p = subprocess.Popen(cmd, stdout=subprocess.PIPE, \
			stdin=subprocess.PIPE)

		cracker = p

		res = p.communicate()[0]
		res = str(res)

		cracker = None
	
		if ("not in dictionary" in res):
			print("No luck")
			u = "%snet/%s/result?part=%s" % \
			    	(url, crack['net'], crack['part'])

			stuff = urlopen(u).read()
			print stuff
		elif "KEY FOUND" in res:
			pw = re.sub("^.*\[ ", "", res)

			i = pw.rfind(" ]")
			if i == -1:
				raise BaseException("Can't parse output")

			pw = pw[:i]

			print("Key for %s is %s" % (crack['net'], pw))

			u = "%snet/%s/result?pass=%s" % (url, crack['net'], pw)
			stuff = urlopen(u).read()
			print stuff
	else:
		cmd = ["pyrit", "-r", cap, "-i", wl,"-b",crack['net'],"attack_passthrough"]
		print "pyrit"
		print cmd
		p = subprocess.Popen(cmd, stdout=subprocess.PIPE, \
			stdin=subprocess.PIPE)

		cracker = p

		res = p.communicate()[0]
		res = str(res)
		print res
		cracker = None
		if ("Password was not found" in res):
			print("No luck")
			u = "%snet/%s/result?part=%s" % \
			    	(url, crack['net'], crack['part'])

			stuff = urlopen(u).read()
			print stuff
		elif "The password is" in res:
			m = re.search("The password is '(.*)'",res)
			pw = m.group(1)

			print("Key for %s is %s" % (crack['net'], pw))

			u = "%snet/%s/result?pass=%s" % (url, crack['net'], pw)
			stuff = urlopen(u).read()
			print stuff			
	return 0

def decompress(fn,fn_decompressed):
	f = gzip.open(fn)
	o = open(fn_decompressed, "wb")
	o.writelines(f)
	o.close()
	f.close()
def setup_dict(crack):
	global url
	bssid = crack['net']
	part = crack['part']

	print("Downloading part %d" % part)

	u = "%sdict/%d" % (url, part)
	print u
	
	stuff = urlopen(u)

	fn_decompressed = "client_dict.txt"
	fn = fn_decompressed+".gz"
	try:
    		os.remove(fn)
	except OSError:
    		pass
	try:
    		os.remove(fn_decompressed)
	except OSError:
    		pass

	f = open(fn, "wb")
	f.write(stuff.read())
	f.close()

	print("Uncompressing dictionary")
	decompress(fn,fn_decompressed)

	return fn_decompressed

def get_cap(crack):
	global url, nets
	fn_decompressed = "dcrack-client.cap" 
	fn = fn_decompressed+".gz"
	try:
    		os.remove(fn)
	except OSError:
    		pass
	try:
    		os.remove(fn_decompressed)
	except OSError:
    		pass
	bssid = crack['net'].upper()
	print("Downloading cap")
	u = "%scap/%s" % (url, bssid)
	print u
	stuff = urlopen(u)

	f = open(fn, "wb")
	f.write(stuff.read())
	f.close()

	print("Uncompressing cap")
	decompress(fn,fn_decompressed)

	nets = {}
	check_cap(fn_decompressed, bssid)


	return fn_decompressed

def process_cap(fn):
	global nets

	nets = {}

	print("Processing cap")
	p = subprocess.Popen(["aircrack-ng", fn], stdout=subprocess.PIPE, \
		stdin=subprocess.PIPE)
	found = False
	while True:
		line = p.stdout.readline()

		try:
			line = line.decode("utf-8")
		except:
			line = str(line)

		if "1 handshake" in line:
			found = True
			parts = line.split()
			b = parts[1].upper()
#			print("BSSID [%s]" % b)
			nets[b] = True

		if (found and line == "\n"):
			break

	p.stdin.write(bytes("1\n", "utf-8"))
	p.communicate()

def check_cap(fn, bssid):
	global nets

	cmd = ["aircrack-ng", "-b", bssid, fn]
	p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stdin=subprocess.PIPE)

	res = p.communicate()[0]
	res = str(res)

	if "No matching network found" not in res:
		nets[bssid] = True

def worker(pyrit):
	while True:
		interval = get_work(pyrit)
		time.sleep(interval)

def set_url():
	global url, port

	if len(sys.argv) < 3:
		print("Provide server addr")
		usage()

	host = sys.argv[2]

	if not ":" in host:
		host = "%s:%d" % (host, port)

	url = "http://" + host + "/" + "dcrack/"

def client(pyrit):
	global cid, cracker, url

	set_url()
	url += "worker/"

	speed = get_speed(pyrit)
	print("Speed", speed)

	cid = get_cid()

	print("CID", cid)

	try_ping(speed)
	t = threading.Thread(target=pinger, args=(speed,))
	t.start()

	while True:
		try:
			do_client(pyrit)
			break
		except URLError:
			print("Conn refused")
			time.sleep(60)

def do_client(pyrit):
	try:
		worker(pyrit)
	except KeyboardInterrupt:
		if cracker:
			cracker.kill()
		print("one more time...")

def upload_file(url, f):
	x  = urlparse(url)
	c = HTTPConnection(x.netloc)

	# XXX not quite HTTP form

	f = open(f, "rb")
	c.request("POST", x.path, f)
	f.close()

	res = c.getresponse()
	stuff = res.read()
	c.close()

	return stuff

def create_dictpart(filenum):
	filename = dictdir+"/%d.txt.gz" % (filenum)
	o = gzip.open(filename, "wb")
	return o


def compress_file(f):
	i = open(f, "rb")
	o = gzip.open(f + ".gz", "wb")
	o.writelines(i)
	o.close()
	i.close()

def send_dict():
	global url

	if len(sys.argv) < 5:
		print("Need dict")
		usage()

	d = sys.argv[4]

	print("Calculating dictionary hash for %s" % d)

	#sha1 = hashlib.sha1()
	#f = open(d, "rb")
	#sha1.update(f.read())
	#f.close()

	#h = sha1.hexdigest()

	#print("Hash is %s" % h)

	#u = url + "dict/" + h + "/status"
	#stuff = urlopen(u).read()

	#if "NO" in str(stuff):
	u = url + "dict/create"
	#print("Compressing dictionary")
	#compress_file(d)
	print("Uploading dictionary")
	upload_file(u, d)

	#print("Setting dictionary to %s" % d)
	#u = url + "dict/" + h + "/set"
	#stuff = urlopen(u).read()

def send_cap():
	global url

	if len(sys.argv) < 5:
		print("Need cap")
		usage()

	cap = sys.argv[4]

	print("Cleaning cap %s" % cap)
	subprocess.Popen(["wpaclean", cap + ".clean", cap], \
	   stderr=subprocess.STDOUT, stdout=subprocess.PIPE).communicate()[0]

	print("Compressing cap")
	compress_file(cap + ".clean")

	u = url + "cap/create"
	upload_file(u, cap + ".clean.gz")

def cmd_crack():
	net_cmd("crack")

def net_cmd(op):
	global url

	if len(sys.argv) < 5:
		print("Need BSSID")
		usage()

	bssid = sys.argv[4]

	print("%s %s" % (op, bssid))
	u = "%snet/%s/%s" % (url, bssid, op)
	stuff = urlopen(u).read()

def cmd_remove():
	net_cmd("remove")

def cmd_status():
	u = "%sstatus" % url
	stuff = urlopen(u).read()

	stuff = json.loads(stuff.decode("utf-8"))

#	print(stuff)
#	print("=============")

	i = 0
	speed = 0
	for c in stuff['clients']:
		i += 1
		speed += c['speed']

	print("Clients:%d\tSpeed:%d\n" % (i, speed))

	for c in stuff['clients']:
		print("%s:%d\n" % (c['name'], c['speed']))

	need = 0

	for n in stuff['nets']:
		out = n['bssid'] + " "
		if "pass" in n:
			out += n['pass']
		else:
			out += " parts:"+str(n['parts'])+ " finished:"+str(n['finished'])+ " inprogress:"+str(n['inprogress'])
		print(out)


def do_cmd():
	global url

	set_url()
	url += "cmd/"

	if len(sys.argv) < 4:
		print("Need CMD")
		usage()

	cmd = sys.argv[3]

	if "dict" in cmd:
		send_dict()
	elif "cap" in cmd:
		send_cap()
	elif "crack" in cmd:
		cmd_crack()
	elif "status" in cmd:
		cmd_status()
	elif "remove" in cmd:
		cmd_remove()
	else:
		print("Unknown cmd %s" % cmd)
		usage()

def main():
	if len(sys.argv) < 2:
		usage()

	cmd = sys.argv[1]

	if cmd == "server":
		server()
	elif cmd == "client":
		client(False)
	elif cmd == "clientp":
		client(True)
	elif cmd == "cmd":
		do_cmd()
	else:
		print("Unknown cmd", cmd)
		usage()

	exit(0)

if __name__ == "__main__":
	main()
