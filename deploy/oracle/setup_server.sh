#!/usr/bin/env bash
# PtoS 발표 시연 서버 설치 (Oracle Cloud Always Free, Ubuntu 24.04, ARM 또는 x86). docs/DEPLOY_ORACLE.md 참고.
#
# 미리 할 것:
#   1) 코드를 /opt/ptos에 둔다:  sudo git clone -b <브랜치> https://github.com/<저장소>.git /opt/ptos
#   2) 화면 빌드 결과를 /opt/ptos/frontend/dist에 둔다(내 PC에서 npm run build 후 scp로 복사).
# 실행:  sudo bash /opt/ptos/deploy/oracle/setup_server.sh <도메인>   예: 140-238-1-2.sslip.io
#
# 이 스크립트는 키를 만들거나 외부 API를 켜지 않는다. /etc/ptos/ptos.env 값은 사용자가 직접 채운다.
set -euo pipefail

DOMAIN="${1:-}"
if [[ -z "$DOMAIN" || ! "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]]; then
  echo "사용법: sudo bash setup_server.sh <도메인>" >&2
  exit 1
fi
if [[ $EUID -ne 0 ]]; then
  echo "sudo로 실행해 주세요." >&2
  exit 1
fi
APP=/opt/ptos
if [[ ! -f "$APP/backend/app/main.py" ]]; then
  echo "$APP 에 PtoS 코드가 없어요. 먼저 git clone 해 주세요." >&2
  exit 1
fi
if [[ ! -f "$APP/frontend/dist/index.html" ]]; then
  echo "$APP/frontend/dist 가 없어요. 내 PC에서 npm run build 후 복사해 주세요." >&2
  exit 1
fi

MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
if (( MEM_MB < 3000 )) && [[ -z "$(swapon --show --noheadings)" ]]; then
  echo "[0/6] 메모리가 ${MEM_MB}MB라 스왑 2GB를 만들어요 (AMD Micro 1GB 서버용)"
  fallocate -l 2G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=2048
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "[1/6] 패키지 설치 (Python, Tesseract, Caddy, 방화벽 저장 도구)"
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv python3-pip tesseract-ocr caddy iptables-persistent

echo "[2/6] 실행 계정과 폴더"
id -u ptos >/dev/null 2>&1 || useradd --system --home /var/lib/ptos --shell /usr/sbin/nologin ptos
install -d -m 700 -o ptos -g ptos /var/lib/ptos
install -d -m 755 /etc/ptos
if [[ ! -f /etc/ptos/ptos.env ]]; then
  install -m 600 -o root -g root "$APP/deploy/oracle/ptos.env.example" /etc/ptos/ptos.env
  echo "  /etc/ptos/ptos.env 를 만들었어요. VAPID 키와 연락처를 직접 채워 주세요."
fi

echo "[3/6] Python 가상환경과 패키지"
python3 -m venv "$APP/.venv"
"$APP/.venv/bin/pip" install --upgrade pip
"$APP/.venv/bin/pip" install -r "$APP/backend/requirements.txt"
if grep -q '^PTOS_MODEL_PATH=' /etc/ptos/ptos.env && (( MEM_MB < 3000 )); then
  echo "  메모리가 ${MEM_MB}MB라 모델(torch)은 설치하지 않아요. /etc/ptos/ptos.env의 PTOS_MODEL_PATH 줄을 지워 주세요."
elif grep -q '^PTOS_MODEL_PATH=' /etc/ptos/ptos.env; then
  echo "  모델을 쓰도록 설정돼 있어 torch·transformers(CPU)를 설치해요."
  "$APP/.venv/bin/pip" install -r "$APP/backend/requirements-embedding.txt" --extra-index-url https://download.pytorch.org/whl/cpu
fi

echo "[4/6] OCR 언어 데이터 (공식 kor·eng, SHA-256 확인)"
TESSERACT_CMD=/usr/bin/tesseract "$APP/.venv/bin/python" "$APP/scripts/setup_ocr.py"
chown -R root:root "$APP"
chmod -R a+rX "$APP"

echo "[5/6] 서비스 등록 (백엔드, Caddy)"
install -m 644 "$APP/deploy/oracle/ptos.service" /etc/systemd/system/ptos.service
sed "s/{\$PTOS_DOMAIN}/$DOMAIN/" "$APP/deploy/oracle/Caddyfile" > /etc/caddy/Caddyfile
systemctl daemon-reload
systemctl enable --now ptos
systemctl restart ptos
systemctl enable caddy
systemctl restart caddy

echo "[6/6] 서버 안 방화벽에서 80·443 열기 (Oracle Ubuntu 이미지는 기본으로 막혀 있어요)"
for port in 80 443; do
  if ! iptables -C INPUT -p tcp -m state --state NEW --dport "$port" -j ACCEPT 2>/dev/null; then
    iptables -I INPUT 5 -p tcp -m state --state NEW --dport "$port" -j ACCEPT
  fi
done
netfilter-persistent save

echo
echo "완료. 확인:"
echo "  curl -s https://$DOMAIN/api/v1/health/ready"
echo "  (family가 live이고, 키를 채웠다면 push도 live여야 해요)"
echo "VCN 보안 목록(Security List)에서 80·443 수신 규칙도 열어야 밖에서 접속돼요."
