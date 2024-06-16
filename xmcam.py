import sys, time
import xmconst
import json, os, subprocess, socket
from struct import pack, unpack
import hashlib
import ffmpeg

if sys.version_info[0] == 2:
    from threading import _Timer as Timer
else:
    from threading import Timer

class RepeatingTimer(Timer):
    def run(self):
        while not self.finished.is_set():
            self.function(*self.args, **self.kwargs)
            self.finished.wait(self.interval)

class XMCam:
    instance = None
    main_socket = None
    socket_timeout = 20
    sid = 0
    sequence = 0
    ip = ''
    port = 0
    username = password = ''
    keepalive_timer = None

    def __init__(self, ip, port, username, password, sid=0, autoconnect=True, instance=None):
        self.ip = ip
        self.port = port
        self.username = username
        self.password = password
        self.sid = sid
        self.instance = instance

        if autoconnect:
            self.connect()

    def __del__(self):
        try:
            self.disconnect()
        except:
            pass

    def is_sub_connection(self):
        return self.instance != None
        
    def connect(self):
        try:
            self.main_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.main_socket.settimeout(self.socket_timeout)
            self.main_socket.connect((self.ip, self.port))
        except Exception as e:
            print(e)
            return False
        return True

    def disconnect(self):
        try:
            self.main_socket.close()
            self._stop_keepalive_interval()
        except:
            pass


    @staticmethod
    def to_dict(json_data):
        data_dict = json.loads(json_data)
        return data_dict

    def _generic_command_head(self, msgid, params):
        pkt = params

        if msgid != xmconst.LOGIN_REQ2 and type(params) != bytes:
            pkt['SessionID'] = self._build_packet_sid()

        cmd_data = self._build_packet(msgid, pkt)
        self.main_socket.send(cmd_data)

        if type(params) == bytes:
            return cmd_data

        response_head = self._get_response_head()
        return response_head
        
    def _generic_command(self, msgid, params):
        response_head = self._generic_command_head(msgid, params)
        out = self._get_response_data(response_head)

        if msgid == xmconst.LOGIN_REQ2 and 'SessionID' in response_head:
            self.sid = response_head['SessionID']

        if out:
            return out

        return None


    def _get_response_head(self):
        data = self.main_socket.recv(4)
        head_flag, version, _, _ = unpack('BBBB', data)

        data = self.main_socket.recv(8)
        sid, seq = unpack('ii', data)

        data = self.main_socket.recv(8)
        channel, endflag, msgid, size = unpack('BBHI', data)

        reply_head = {
            'Version': version,
            'SessionID': sid,
            'Sequence': seq,
            'MessageId': msgid,
            'Content_Length': size
        }

        self.sequence = seq

        return reply_head

    def _get_response_data(self, reply_head):
        reply = reply_head
        length = reply['Content_Length']
        out = bytearray()  # Используем bytearray для накопления байтов

        for i in range(0, length):
            data = self.main_socket.recv(1)
            out.extend(data)

        # Попробуем декодировать все байты сразу
        try:
            return out.decode('utf-8').rstrip('\x00')
        except UnicodeDecodeError:
            # Если произошла ошибка, возвращаем сырые байты в виде строки
            return out.decode('latin-1').rstrip('\x00')  # Можно использовать другой кодек, например 'latin-1'

    def _build_packet_sid(self):
        return '0x%08x' % self.sid

    def _build_packet(self, ptype, data):
        pkt_type = ptype
        pkt_prefix_1 = (0xff, 0x01, 0x00, 0x00)
        pkt_prefix_2 = (0x00, 0x00, 0x00, 0x00)

        header = pack('B'*len(pkt_prefix_1), *pkt_prefix_1)
        header += pack('I', self.sid)
        header += pack('B'*len(pkt_prefix_2), *pkt_prefix_2)
        header += pack('H', 0) + pack('H', pkt_type)

        # If data is bytes, designed for sending stream bytes to server
        if type(data) == bytes:
            pkt_data = data
            pkt_data = header + pack('I', len(pkt_data)) + pkt_data
        else:
            pkt_data = json.dumps(data)
            pkt_data = header + pack('I', len(pkt_data)) + bytes(pkt_data.encode('ascii'))

        return pkt_data

    def _start_keepalive_interval(self):
        self.keepalive_timer = RepeatingTimer(20.0, self._interval_keepalive)
        self.keepalive_timer.start()

    def _interval_keepalive(self):
        pkt = {
            "Name" : "KeepAlive"
        }
        response = self._generic_command(xmconst.KEEPALIVE_REQ, pkt)
        print(response)

    def create_sub_connection(self, autoconnect=False):
        subconn = XMCam(self.ip, self.port, self.username, self.password, sid=self.sid, instance=self, autoconnect=autoconnect)
        return subconn

    def sofia_hash(self, msg):
        h = ""
        m = hashlib.md5()
        m.update(msg.encode('utf-8'))  # Кодируем строку в байты
        msg_md5 = m.digest()
        for i in range(8):
            n = (msg_md5[2 * i] + msg_md5[2 * i + 1]) % 0x3e  # Не нужно использовать ord для байтов
            if n > 9:
                if n > 35:
                    n += 61
                else:
                    n += 55
            else:
                n += 0x30
            h += chr(n)
        return h
    def cmd_login(self):
        pkt = {
            'EncryptType': 'MD5',
            'LoginType': 'DVRIP-Web',
            'PassWord': self.sofia_hash(self.password),
            'UserName': self.username
        }

        response = self._generic_command(xmconst.LOGIN_REQ2, pkt)
        respdict = self.to_dict(response)

        if not self.is_sub_connection() and respdict != None and 'Ret' in respdict and respdict['Ret'] == 100:
            self._start_keepalive_interval()
        else:
            print(__name__, 'Cannot start keepalive')

        return response

    def cmd_talk_claim(self):
        assert self.is_sub_connection(), 'cmd_talk_claim need run on a sub connection'

        pkt = {
            "Name": "OPTalk",
            "OPTalk": {
                "Action": "Claim",
                "AudioFormat": {
                    "BitRate": 0,
                    "EncodeType": "G711_ALAW",
                    "SampleBit": 8,
                    "SampleRate": 8
                }
            }
        }

        response = self._generic_command(xmconst.TALK_CLAIM, pkt)
        return response

    def cmd_talk_send_stream(self, data):
        assert isinstance(data, list), 'Data should be a list of PCM bytes'
        for chunk in data:
            assert isinstance(chunk, bytes), 'Each chunk should be of bytes type'
            final_data = b'\x00\x00\x01\xfa\x0e\x02\x40\x01' + chunk
            sent = self._generic_command_head(xmconst.TALK_CU_PU_DATA, final_data)
            time.sleep(0.04)  # добавляем задержку 40 миллисекунд между отправкой чанков
        return sent

    def cmd_talk_start(self):
        pkt = {
            "Name" : "OPTalk",
            "OPTalk" : {
                "Action" : "Start",
                "AudioFormat" : {
                    "BitRate" : 128,
                    "EncodeType" : "G711_ALAW",
                    "SampleBit" : 8,
                    "SampleRate" : 8000
                }
            }
        }

        response = self._generic_command(xmconst.TALK_REQ, pkt)
        return response

    def cmd_talk_stop(self):
        pkt = { 
            "Name" : "OPTalk", 
            "OPTalk" : { 
                "Action" : "Stop", 
                "AudioFormat" : { 
                    "BitRate" : 128, 
                    "EncodeType" : "G711_ALAW", 
                    "SampleBit" : 8, 
                    "SampleRate" : 8000 
                }
            }
        }

        response = self._generic_command(xmconst.TALK_REQ, pkt)
        return response

    @staticmethod
    def talk_convert_to_pcm(src, volume=1.0,
                            args=('-y', '-f', 'alaw', '-ar', '8000', '-ac', '1')):
        if not os.path.exists(src):
            return (False, 'Нет исходного файла')

        dst_final = src + '.pcm'

        try:
            stream = ffmpeg.input(src)
            if volume != 1.0:
                stream = ffmpeg.filter(stream, 'volume', volume=volume)


            stream = ffmpeg.output(stream, dst_final, format='alaw', ar='8000', ac='1')
            ffmpeg.run(stream, overwrite_output=True)
        except ffmpeg.Error as e:
            return (False, str(e))

        return (os.path.exists(dst_final), dst_final)

    @staticmethod
    def talk_get_chunks(pcmfile, chunk_size=320):
        retdata = None
        try:
            pcmdata = open(pcmfile, 'rb').read()
            data = [pcmdata[i:i+chunk_size] for i in range(0, len(pcmdata), chunk_size)]
            retdata = data
        except:
            print('Got an exception on talk_get_chunks')

        return retdata
