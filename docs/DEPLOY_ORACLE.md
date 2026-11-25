# 발표 시연 서버 배포 (Oracle Cloud Always Free)

가족 보호(초대 링크·웹 푸시)를 실제 휴대폰 두 대로 보여 주려면 **공개 https 주소**가 필요해요.
이 문서는 Oracle Cloud의 무료 서버 한 대에 PtoS 전체(화면·백엔드·OCR·가족 보호 DB)를 올리는 방법이에요.

- **비상업 발표 시연용**이에요. 주소는 팀원과 평가자에게만 알려 주고 공개 운영 서비스로 쓰지 않아요(AGENTS.md Safe Browsing 조건).
- 키·비밀번호는 서버의 `/etc/ptos/ptos.env`에만 넣어요. 채팅·코드·문서·커밋·저장소 안 `.env`에 쓰지 않아요.
- 서버 하나, 프로세스 하나(`--workers` 없음)로 돌려요.

```
휴대폰 ──https──▶ [Oracle 무료 서버]
                   ├─ Caddy: 인증서 자동 발급, 화면 파일(frontend/dist), /api → 127.0.0.1:8000
                   ├─ FastAPI(uvicorn 1개): 분석 + 가족 보호 API
                   ├─ SQLite: /var/lib/ptos/family.db (가족 연결·확인 요청·의견, 7일 보관)
                   └─ Tesseract 5(kor+eng), 선택: 경량 모델 폴더
```

## 1. Oracle 계정과 서버 만들기 (직접)

1. Oracle Cloud 가입. 본인 확인용으로 카드를 등록해요. 유료 전환(Upgrade)을 하지 않으면 Always Free 자원만 쓸 수 있어요. 가입 화면의 조건을 꼭 확인해 주세요.
2. **홈 리전은 나중에 바꿀 수 없어요.** 서울(ap-seoul-1) 또는 춘천(ap-chuncheon-1)을 고르세요.
3. Compute → Instances → Create instance
   - Image: **Canonical Ubuntu 24.04**
   - Shape: **Ampere (VM.Standard.A1.Flex)**, 2 OCPU / 12GB 메모리 정도면 충분해요(무료 한도 안).
     "Out of capacity"가 나오면 시간을 두고 다시 시도하거나 OCPU를 줄여 보세요. **발표 직전이 아니라 미리** 만들어 두세요.
   - SSH 키: "Generate a key pair"로 내려받아 안전한 곳에 보관해요(저장소에 넣지 않아요).
   - Public IPv4 주소 할당을 켜요.
4. 서버의 공인 IP를 확인해요. 예: `140.238.1.2`
5. **VCN 방화벽 열기:** Networking → Virtual cloud networks → 서버의 VCN → Security Lists → Default → Add Ingress Rules
   - Source CIDR `0.0.0.0/0`, TCP, Destination port `80`
   - Source CIDR `0.0.0.0/0`, TCP, Destination port `443`
   (22번 SSH는 기본으로 열려 있어요.)

## 2. 주소(도메인) 정하기

도메인이 없으면 IP로 만드는 무료 주소를 써요. IP의 점을 `-`로 바꿔요.

- `140.238.1.2` → `140-238-1-2.sslip.io`

Caddy가 이 주소로 Let's Encrypt 인증서를 자동으로 받아요. 인증서 발급이 계속 실패하면(공용 주소의 발급 한도 등) DuckDNS 같은 무료 도메인이나 가진 도메인을 쓰세요.

## 3. 내 PC에서 화면 빌드

```bash
cd frontend
npm ci
npm run build          # frontend/dist 생성
```

## 4. 서버에 코드와 화면 올리기

내 PC(Git Bash)에서. `<키 파일>`, `<IP>`, `<브랜치>`는 바꿔 넣어요.

```bash
ssh -i <키 파일> ubuntu@<IP>
# 서버 안에서
sudo git clone -b <브랜치> https://github.com/spoonyerin/PtoS.git /opt/ptos
exit
# 다시 내 PC에서: 화면 빌드 결과 복사
scp -i <키 파일> -r frontend/dist ubuntu@<IP>:/tmp/ptos-dist
ssh -i <키 파일> ubuntu@<IP> "sudo rm -rf /opt/ptos/frontend/dist && sudo mv /tmp/ptos-dist /opt/ptos/frontend/dist"
```

저장소가 비공개면 서버에서 `git clone` 대신 내 PC에서 `git archive`로 묶어 `scp`로 옮겨도 돼요.

## 5. 설치 스크립트 실행

```bash
ssh -i <키 파일> ubuntu@<IP>
sudo bash /opt/ptos/deploy/oracle/setup_server.sh 140-238-1-2.sslip.io
```

스크립트가 하는 일: Python·Tesseract·Caddy 설치, `ptos` 실행 계정, 가상환경과 패키지, OCR 언어 데이터(SHA-256 확인),
`ptos.service`·Caddy 등록, 서버 안 방화벽(iptables)에서 80·443 열기.
`/etc/ptos/ptos.env`가 없으면 예시 파일로 만들어요(권한 600).

## 6. VAPID 키 만들고 환경 변수 채우기 (직접)

서버 안에서:

```bash
sudo /opt/ptos/.venv/bin/python /opt/ptos/backend/generate_vapid_keys.py
sudo nano /etc/ptos/ptos.env
```

- 출력된 두 줄(`PTOS_VAPID_PUBLIC_KEY=…`, `PTOS_VAPID_PRIVATE_KEY=…`)을 붙여 넣어요.
- `PTOS_VAPID_SUBJECT=mailto:<팀 메일>`을 채워요. 푸시 서비스가 문제를 알릴 연락처예요.
- 키를 다시 만들면 모든 기기에서 알림을 다시 켜야 해요.

```bash
sudo systemctl restart ptos
curl -s https://140-238-1-2.sslip.io/api/v1/health/ready
```

`"family":"live"`와 `"push":"live"`가 나오면 준비됐어요.

## 7. (선택) 경량 모델 올리기

모델 폴더(manifest.json, model.safetensors 등)는 저장소 밖 파일이라 직접 옮겨야 해요(학습 데이터 CC BY-NC 4.0, 커밋 금지).

```bash
scp -i <키 파일> -r <내 PC의 모델 폴더> ubuntu@<IP>:/tmp/ptos-model
ssh -i <키 파일> ubuntu@<IP> "sudo mv /tmp/ptos-model /opt/ptos-model && sudo chmod -R a+rX /opt/ptos-model"
```

`/etc/ptos/ptos.env`에 `PTOS_MODEL_PATH=/opt/ptos-model/manifest.json`을 넣고 `setup_server.sh`를 한 번 더 실행하면 torch·transformers(CPU)를 설치해요.
ARM 서버에서 설치·로드가 되는지는 **아직 확인하지 않았어요.** 로드에 실패해도 서버는 규칙 결과만으로 동작해요(`analysis_stages`의 모델 단계가 `unavailable`).

## 8. 휴대폰에서 확인 (발표 전에 꼭)

| 기기 | 알림 받는 조건 |
| --- | --- |
| Android Chrome | 주소를 열고 "이 휴대폰에서 알림 받기"를 켜요. |
| iPhone (iOS 16.4 이상) | Safari로 주소를 열고 공유 버튼 → **"홈 화면에 추가"** → 홈 화면의 PtoS 아이콘으로 열어서 알림을 켜요. Safari 탭 안에서는 알림을 켤 수 없어요. |

확인 순서:
1. 휴대폰 A(고령자): 홈 → 가족 보호 → 프리미엄 시작하기(시연용) → 가족 연결하기 → 초대 보내기
2. 휴대폰 B(보호자): 초대 링크 열기 → 수락 → 알림 켜기
3. 휴대폰 A: 알림 켜기 → 문자 확인 → 분석 → 가족에게 공유 → 공유하기
4. 휴대폰 B: 알림 → 요청 열기 → 의견 보내기
5. 휴대폰 A: 알림 → 의견 확인. 자동 알림도 켜서 '위험' 결과로 확인

알림은 휴대폰의 방해 금지·절전 모드, 브라우저 알림 권한에 따라 늦거나 오지 않을 수 있어요. 그래서 화면 안에서도 상태를 다시 확인해요(공유 창 5초, 요청 화면 8초, 홈 20초 간격).

## 9. 업데이트와 정리

```bash
# 코드 업데이트
ssh -i <키 파일> ubuntu@<IP> "cd /opt/ptos && sudo git pull && sudo systemctl restart ptos"
# 화면 업데이트는 3·4단계의 빌드·복사를 다시 해요.
# 로그(고정 코드만 남아요)
ssh -i <키 파일> ubuntu@<IP> "sudo journalctl -u ptos -n 50"
# 가족 보호 기록 전부 지우기(시연 초기화)
ssh -i <키 파일> ubuntu@<IP> "sudo systemctl stop ptos && sudo rm -f /var/lib/ptos/family.db* && sudo systemctl start ptos"
```

발표가 끝나면 Oracle 콘솔에서 인스턴스를 **Terminate**(부트 볼륨 삭제 포함)해서 DB와 키를 함께 지워요.

## 10. 예비: 노트북 + Cloudflare Tunnel

Oracle 서버를 못 만들었거나 발표 당일 문제가 생기면 노트북에서 같은 코드를 띄우고 터널로 https 주소를 받아요.
`cloudflared` 설치는 직접 해 주세요.

```bash
# 1) 터널 먼저 연결하고 출력된 주소(예: https://abc-def.trycloudflare.com)를 확인
cloudflared tunnel --url http://localhost:5173
# 2) 백엔드 (다른 Git Bash). 가족 DB는 저장소 밖 경로로.
export TESSERACT_CMD='C:/Program Files/Tesseract-OCR/tesseract.exe'
export PTOS_FAMILY_DB_PATH="$HOME/ptos-family.db"
export PTOS_PUSH_MODE=live-webpush PTOS_VAPID_SUBJECT=mailto:<팀 메일>
export PTOS_VAPID_PUBLIC_KEY=<생성한 값> PTOS_VAPID_PRIVATE_KEY=<생성한 값>
cd backend && ../.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
# 3) 화면 (또 다른 Git Bash). 터널 호스트 하나만 허용한다.
cd frontend && npm run build && PTOS_TUNNEL_HOST=abc-def.trycloudflare.com npx vite preview
```

- VAPID 키는 `../.venv/Scripts/python.exe backend/generate_vapid_keys.py`로 만들어요. 셸 기록에 남지 않게 주의하고, 끝나면 터미널을 닫아요.
- 빠른 터널 주소는 실행할 때마다 바뀌어요. 바뀌면 초대 링크와 알림 구독을 다시 만들어야 해요.
- 노트북이 잠들면 접속이 끊겨요. 발표 중에는 절전을 꺼 두세요.
