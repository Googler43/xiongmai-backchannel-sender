from xmcam import *


CAM_IP = '192.168.0.106'
CAM_PORT = 34567
user = 'admin'
passwd = ''
file = 'Eurythmics, Annie Lennox, Dave Stewart - Sweet Dreams (Are Made of This)_(Muz-Monster.ru).mp3'
volume_music = 0.4
size_packet = 320

if __name__ == '__main__':
    xm = XMCam(CAM_IP, CAM_PORT, user, passwd)
    login = xm.cmd_login()
    sub_conn = xm.create_sub_connection(autoconnect=True)
    response = sub_conn.cmd_talk_claim()
    print(response)
    print(login)

    pcm_conversion_result = xm.talk_convert_to_pcm(file, volume=volume_music)
    if not pcm_conversion_result[0]:
        print("PCM Conversion failed:", pcm_conversion_result[1])
        sys.exit(1)

    pcm_file = pcm_conversion_result[1]
    print("PCM File:", pcm_file)

    with open(pcm_file, 'rb') as f:
        pcm_data = f.read()

    chunks = xm.talk_get_chunks(pcm_file, chunk_size=size_packet)
    if not chunks:
        print("Failed to get PCM chunks")
        sys.exit(1)

    sub_conn.cmd_talk_start()

    sub_conn.cmd_talk_send_stream(chunks)

    # Останавливаем передачу аудиопотока
    sub_conn.cmd_talk_stop()