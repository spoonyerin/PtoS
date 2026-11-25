"""웹 푸시용 VAPID 키 한 쌍을 만들어 화면에 한 번만 출력한다(발표 시연 한정, docs/DEPLOY_ORACLE.md).

- 파일로 저장하지 않는다. 출력된 두 줄을 서버의 /etc/ptos/ptos.env에만 붙여 넣는다.
- 채팅·코드·문서·커밋·.env 파일(저장소 안)에 붙여 넣지 않는다.
- 비공개 키가 새면 이 스크립트로 새 키를 만들고, 모든 기기에서 알림을 다시 켜야 한다.
"""

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def main() -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    private_raw = key.private_numbers().private_value.to_bytes(32, "big")
    public_raw = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    print(f"PTOS_VAPID_PUBLIC_KEY={b64url(public_raw)}")
    print(f"PTOS_VAPID_PRIVATE_KEY={b64url(private_raw)}")


if __name__ == "__main__":
    main()
