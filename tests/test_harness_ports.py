import socket

from harness.core import ports


def test_free_port_is_bindable():
    p = ports.free_port()
    assert 1024 < p < 65536
    # 반환된 포트에 실제로 바인드 가능해야 한다(회수됨)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", p))
    s.close()


def test_free_port_varies():
    # 서로 다른 두 호출이 대체로 다른 포트를 준다(연속 점유 방지)
    a = ports.free_port()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", a))
    b = ports.free_port()
    s.close()
    assert b != a
