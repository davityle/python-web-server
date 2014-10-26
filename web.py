import errno
import os
import select
import socket
import sys
import traceback
import time
import argparse
from wsgiref.handlers import format_date_time
from datetime import datetime
from time import mktime
from time import strftime

seconds = lambda: int(time.time())


class HttpRequest:

    def __init__(self, method, url, version, headers, body, is_complete):
        self.method = method
        self.url = url
        self.version = version
        self.headers = headers
        self.body = body
        self.is_complete = is_complete

    def append(self, data):
        self.body += data

    def body_complete(self):
        return len(self.body) == int(self.headers[WebServer.content_length_header])


# noinspection PyAttributeOutsideInit
class WebServer:

    server_header = 'Server: Tyler-Davis-Awesome-Web-Server-Even-Though-It-Is-In-Python\r\n'
    content_length_header = 'Content-Length:'
    host_header = 'Host:'
    content_type_header = 'Content-Type:'
    date_header = 'Date:'
    last_modified_header = 'Last-Modified:'

    def __init__(self, port):
        self.read_conf()
        self.port = port
        self.open_socket()
        self.clients = {}
        self.size = 10024
        self.timeout = int(self.parameter['timeout'])

    def read_conf(self):
        self.hosts = {}
        self.media = {}
        self.parameter = {}
        with open('web.conf') as conf:
            for line in conf:
                split = line.split(' ')
                if split[0] == 'host':
                    self.hosts[split[1]] = split[2].strip()
                elif split[0] == 'media':
                    self.media[split[1]] = split[2].strip()
                elif split[0] == 'parameter':
                    self.parameter[split[1]] = split[2].strip()

    def open_socket(self):
        try:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server.bind(('', self.port))
            self.server.listen(5)
            self.server.setblocking(0)
        except socket.error, (value, message):
            if self.server:
                self.server.close()
            print "Could not open socket: " + message
            sys.exit(1)


    def run(self):
        self.poller = select.epoll()
        self.pollmask = select.EPOLLIN | select.EPOLLHUP | select.EPOLLERR
        self.poller.register(self.server, self.pollmask)
        while True:
            try:
                fds = self.poller.poll(timeout=self.timeout)
            except:
                return

            for (fd, event) in fds:
                if event & (select.POLLHUP | select.POLLERR):
                    self.handle_error(fd)
                    continue
                if fd == self.server.fileno():
                    self.handle_server()
                    continue
                self.handle_client(fd)

                to_delete = []
                for fileNo, client in self.clients.iteritems():
                    inactive_time = seconds() - client[1]
                    if inactive_time >= self.timeout:
                        to_delete.append(fileNo)

                for fileNo in to_delete:
                    self.close_client(fileNo)

    def close_client(self, fd):
        self.poller.unregister(fd)
        self.clients[fd][0].close()
        del self.clients[fd]

    def handle_error(self, fd):
        self.poller.unregister(fd)
        if fd == self.server.fileno():
            self.server.close()
            self.open_socket()
            self.poller.register(self.server, self.pollmask)
        else:
            self.clients[fd][0].close()
            del self.clients[fd]

    def handle_server(self):
        while True:
            try:
                (client, address) = self.server.accept()
            except socket.error, (value, message):
                if value == errno.EAGAIN or errno.EWOULDBLOCK:
                    return
                print traceback.format_exc()
                sys.exit()

            client.setblocking(0)
            client_data = ''
            self.clients[client.fileno()] = [client, seconds(), client_data]
            self.poller.register(client.fileno(), self.pollmask)

    def handle_client(self, fd):
        client = self.clients[fd]
        try:
            data = client[0].recv(self.size)
            client[1] = seconds()
        except socket.error, (value, message):
            if value == errno.EAGAIN or errno.EWOULDBLOCK:
                return
            print traceback.format_exc()
            sys.exit()

        if data:
            if len(client) == 3:
                client[2] += data
                if '\r\n\r\n' in client[2]:
                    result = self.parse_http(client[2])
                    if type(result) is str:
                        client[0].send(result)
                        # self.close_client(fd)
                    elif result.is_complete:
                        self.send_response(client, self.respond_get(result), fd)
                    else:
                        client.append(result)
                    client[2] = ''
            else:
                request = client[3]
                request.append(data)
                if request.body_complete():
                    self.send_response(client, self.respond_get(request), fd)
                    del client[3]

        else:
            self.close_client(fd)

    def send_response(self, client, response, fd):
        # print response
        client[0].send(response)
        # self.close_client(fd)

    def parse_http(self, request):
        try:
            # print request
            http_and_body = request.split('\r\n\r\n')
            lines = http_and_body[0].split('\r\n')
            request_line = lines[0].split(' ')
            del lines[0]
            headers = {}
            for line in lines:
                split = line.split(' ')
                headers[split[0]] = split[1]

            complete = False
            body = ''
            if self.content_length_header in headers:
                if len(http_and_body) == 2:
                    body = http_and_body[1]
                    if len(body) == int(headers[self.content_length_header]):
                        complete = True
            else:
                complete = True

            return HttpRequest(request_line[0], request_line[1], ' '.join(request_line[2:]), headers, body, complete)

        except:
            return WebServer.respond_400()

    @staticmethod
    def respond_400():
        body = '<h1>400 Bad Request</h1>'
        length = str(len(body))
        return WebServer.append_static_headers('HTTP/1.1 400 Bad Request\r\n' + WebServer.server_header + WebServer.content_length_header + ' ' + length + '\r\n') + body

    @staticmethod
    def respond_403():
        body = '<h1>403 Forbidden</h1>'
        length = str(len(body))
        return WebServer.append_static_headers('HTTP/1.1 403 Forbidden\r\n' + WebServer.server_header + WebServer.content_length_header + ' ' + length + '\r\n') + body

    @staticmethod
    def respond_404():
        body = '<h1>404 Not Found</h1>'
        length = str(len(body))
        return WebServer.append_static_headers('HTTP/1.1 404 Not Found\r\n' + WebServer.server_header + WebServer.content_length_header + ' ' + length + '\r\n') + body

    @staticmethod
    def respond_500():
        body = '<h1>500 Internal Server Error</h1>'
        length = str(len(body))
        return WebServer.append_static_headers('HTTP/1.1 500 Internal Server Error' + WebServer.server_header + WebServer.content_length_header + ' ' + length + '\r\n') + body

    @staticmethod
    def respond_501():
        body = '<h1>501 Not Implemented</h1>'
        length = str(len(body))
        return WebServer.append_static_headers('HTTP/1.1 501 Not Implemented\r\n' + WebServer.server_header + WebServer.content_length_header + ' ' + length + '\r\n') + body

    @staticmethod
    def append_static_headers(response):
        now = datetime.now()
        stamp = mktime(now.timetuple())
        response += WebServer.date_header + ' ' + format_date_time(stamp) + '\r\n'
        response += WebServer.content_type_header + ' text/html\r\n'
        response += WebServer.last_modified_header + ' ' + format_date_time(stamp) + '\r\n\r\n'
        return response


    def respond_get(self, request):
        try:
            if request.method != 'GET':
                return WebServer.respond_501()

            response = 'HTTP/1.1 200 OK\r\n' + WebServer.server_header

            if WebServer.host_header in request.headers:
                host = request.headers[WebServer.host_header].split(':')
                if host[0] in self.hosts:
                    file_name = self.hosts[host[0]]
                else:
                    file_name = self.hosts['default']
            else:
                file_name = self.hosts['default']

            if request.url == '/':
                file_name += '/index.html'
            else:
                file_name += request.url

            if os.path.isfile(file_name):
                body = open(file_name, "rb").read()
            else:
                return WebServer.respond_404()

            extension = os.path.splitext(file_name)[1][1:]
            if extension in self.media:
                response += WebServer.content_type_header + ' ' + self.media[extension] + '\r\n'

            now = datetime.now()
            stamp = mktime(now.timetuple())
            response += WebServer.date_header + ' ' + format_date_time(stamp) + '\r\n'

            stamp = mktime(datetime.strptime(time.ctime(os.path.getmtime(file_name)), "%a %b %d %H:%M:%S %Y").timetuple())
            response += WebServer.last_modified_header + ' ' + format_date_time(stamp) + '\r\n'

            length = str(len(body))
            response += WebServer.content_length_header + ' ' + length + '\r\n\r\n' + body

            return response
        except Exception, err:
            if err[0] == 13:
                return WebServer.respond_403()
            print traceback.format_exc()
            return WebServer.respond_500()


class Main:
    def __init__(self):
        self.parse_arguments()

    def parse_arguments(self):
        parser = argparse.ArgumentParser(prog='Web Server', description='A web server', add_help=True)
        parser.add_argument('-p', '--port', type=int, action='store', help='port the server will bind to', default=3000)
        self.args = parser.parse_args()

    def run(self):
        p = WebServer(self.args.port)
        p.run()

if __name__ == "__main__":
    m = Main()
    m.parse_arguments()
    try:
        m.run()
    except KeyboardInterrupt:
        pass