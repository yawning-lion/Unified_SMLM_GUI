from ctypes import WinDLL, create_string_buffer


msg = "controller.connect 5"
print(msg)
msg_2 = msg.encode('utf-8')
print(msg_2)
msg_3 = create_string_buffer(msg_2)
print(msg_3)

msg_4 = b'\xd0\x96q\x10\x87\x02'
print(msg_4.decode('latin-1'))    # 没用