# Pi Network Lockup Monitor (PI_LockupMonitor)

이 프로그램은 Pi Network 메인넷의 배포 지갑(`GABT7EM...`)에서 발생하는 마이그레이션 트랜잭션을 실시간으로 분석하여, 사용자들의 락업 기간별 통계를 추출하는 파이썬 기반 도구입니다.

## 주요 기능
- **실시간 데이터 추출**: Pi 메인넷 Horizon API를 통해 최신 마이그레이션 데이터를 수집합니다.
- **병렬 데이터 수집 (New)**: `-d` 파라미터로 지정된 일수별로 스레드를 나누어 병렬로 데이터를 가져와 분석 속도를 획기적으로 향상시켰습니다.
- **락업 기간 정밀 분석**: `predicate.not.rel_before` 필드를 추적하여 시스템 챌린지 기간을 제외한 사용자의 실제 락업 기간만 추출합니다.
- **기간별 버킷 분류**:
  - **Unlocked**: 락업 없음 (2일 미만)
  - **2 Weeks**: 약 2주 전후 (2일 ~ 30일)
  - **6 Months**: 약 6개월 전후 (50일 ~ 70일)
  - **1 Year**: 약 1년 전후 (330일 ~ 390일)
  - **3 Year**: 400일 이상 (3년 락업 포함)
- **가변 기간 분석**: `-d` 파라미터를 통해 최근 1일부터 수일간의 데이터를 자유롭게 분석할 수 있습니다.

## 성능 최적화
- **멀티스레딩**: 최대 10개의 워커 스레드를 사용하여 대량의 트랜잭션 데이터를 동시에 처리합니다.
- **지능적 경계 계산**: 각 날짜별 렛저(Ledger) 시퀀스를 미리 계산하여 API 호출 시 불필요한 데이터 조회를 최소화합니다.

## 설치 방법
Python 3.x 환경에서 다음 명령어를 실행하여 필요한 라이브러리를 설치합니다.

```bash
pip install requests
```

## 사용 방법
기본적으로 최근 24시간(1일)의 통계를 보여줍니다.

```bash
# 기본 실행 (최근 1일)
python3 pi_stats.py

# 특정 기간 지정 (예: 최근 7일, 병렬 처리 적용)
python3 pi_stats.py -d 7
```

## 실행 결과 예시
```text
Parallelizing data fetch for the last 1 day(s) for account: GABT7EM...
Determining day boundaries...
Starting 1 worker threads...
Fetched 10542 operations in 32.45 seconds.

Summary (Last 1 days):
Bucket          | Wallets    | Total Pi        | % of Total
------------------------------------------------------------
Unlocked        | 0          | 0.00            |       0.00%
2 Weeks         | 7552       | 6274029.67      |      37.88%
6 Months        | 1031       | 962005.98       |       5.81%
1 Year          | 1457       | 1638664.20      |       9.89%
3 Year          | 5113       | 7689166.11      |      46.42%
```

## 라이선스
MIT License
