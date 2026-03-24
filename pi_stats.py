import requests
import argparse
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

DAY_SEC = 86400

def get_bucket(duration_seconds):
    """
    Maps a duration in seconds to one of these buckets:
    - Unlocked: < 2 days
    - 2 Weeks: 2 days to 30 days
    - 6 Months: 50 days to 70 days
    - 1 Year: 330 days to 390 days
    - 3 Year: >= 400 days
    (Gaps are categorized as the closest lower bucket)
    """
    days = duration_seconds / DAY_SEC
    
    if days < 2:
        return "Unlocked"
    elif days < 50:
        return "2 Weeks"
    elif days < 330:
        return "6 Months"
    elif days < 400:
        return "1 Year"
    else:
        return "3 Year"

def parse_operation(op_json):
    """
    Parses a Horizon API operation JSON object.
    Filters for 'create_claimable_balance' type and extracts relevant data.
    """
    if op_json.get('type') != 'create_claimable_balance':
        return None

    def to_timestamp(iso_str):
        if not iso_str:
            return None
        return datetime.fromisoformat(iso_str.replace('Z', '+00:00')).timestamp()

    amount = float(op_json.get('amount', 0))
    created_at_str = op_json.get('created_at')
    created_at_ts = to_timestamp(created_at_str)

    abs_before_ts = None
    rel_before_sec = None
    wallet = None
    try:
        claimants = op_json.get('claimants', [])
        if claimants:
            wallet = claimants[0].get('destination')
            for claimant in claimants:
                predicate = claimant.get('predicate', {})
                not_clause = predicate.get('not', {})
                if not_clause:
                    wallet = claimant.get('destination')
                    rel_before_val = not_clause.get('rel_before')
                    if rel_before_val is not None:
                        rel_before_sec = int(rel_before_val)
                    if rel_before_sec is None:
                        abs_before_str = not_clause.get('abs_before')
                        if abs_before_str:
                            abs_before_ts = to_timestamp(abs_before_str)
                    break
    except (AttributeError, KeyError, ValueError):
        pass

    duration = 0
    if rel_before_sec is not None:
        duration = rel_before_sec
    elif abs_before_ts and created_at_ts:
        duration = max(0, abs_before_ts - created_at_ts)

    return {
        'amount': amount,
        'created_at': created_at_ts,
        'duration': duration,
        'wallet': wallet
    }

def get_latest_ledger():
    url = "https://api.mainnet.minepi.com/ledgers?order=desc&limit=1"
    response = requests.get(url)
    response.raise_for_status()
    data = response.json()
    record = data['_embedded']['records'][0]
    return {
        'sequence': record['sequence'],
        'closed_at': datetime.fromisoformat(record['closed_at'].replace('Z', '+00:00')).timestamp()
    }

def get_ledger_boundary_cursor(target_ts, latest_ledger):
    # Estimate ledger sequence (Pi Network: ~5.1s per ledger)
    diff_sec = latest_ledger['closed_at'] - target_ts
    est_seq = latest_ledger['sequence'] - int(diff_sec / 5.1)
    
    # Refine the sequence to be closer to target_ts
    try:
        url = f"https://api.mainnet.minepi.com/ledgers/{est_seq}"
        resp = requests.get(url)
        resp.raise_for_status()
        l_data = resp.json()
        seq = l_data['sequence']
    except:
        seq = est_seq
    
    # Return cursor for (seq + 1) which is a boundary including all ops in 'seq'
    return (seq + 1) << 32

def fetch_data_chunk(wallet_address, start_cursor, end_cursor):
    """
    Fetches operations from start_cursor down to end_cursor (exclusive).
    """
    base_url = f"https://api.mainnet.minepi.com/accounts/{wallet_address}/operations?order=desc&limit=200"
    url = base_url
    if start_cursor:
        url += f"&cursor={start_cursor}"
    
    all_ops = []
    while url:
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            records = data.get('_embedded', {}).get('records', [])
            
            if not records:
                break
                
            for op in records:
                op_id = int(op['id'])
                if end_cursor and op_id <= end_cursor:
                    return all_ops
                all_ops.append(op)
            
            url = data.get('_links', {}).get('next', {}).get('href')
        except requests.exceptions.RequestException as e:
            print(f"Error fetching chunk: {e}")
            break
            
    return all_ops

def main():
    parser = argparse.ArgumentParser(description="Fetch Pi lockup statistics in parallel by day.")
    parser.add_argument("-d", "--days", type=int, default=1, help="Number of days to fetch data for (default: 1)")
    args = parser.parse_args()

    address = "GABT7EMPGNCQSZM22DIYC4FNKHUVJTXITUF6Y5HNIWPU4GA7BHT4GC5G"
    print(f"Parallelizing data fetch for the last {args.days} day(s) for account: {address}")
    
    # 1. Determine boundaries
    print("Determining day boundaries...")
    try:
        latest = get_latest_ledger()
    except Exception as e:
        print(f"Failed to fetch latest ledger: {e}")
        return

    now_ts = latest['closed_at']
    boundaries = [None] # B0 = latest
    for i in range(1, args.days + 1):
        target_ts = now_ts - (i * DAY_SEC)
        cursor = get_ledger_boundary_cursor(target_ts, latest)
        boundaries.append(cursor)
    
    # 2. Dispatch threads
    # Limit max threads to something reasonable, e.g., 10 or the number of days.
    max_workers = min(args.days, 10)
    all_fetched_ops = []
    
    print(f"Starting {max_workers} worker threads...")
    start_time = time.time()
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for i in range(args.days):
            start_cursor = boundaries[i]
            end_cursor = boundaries[i+1]
            futures.append(executor.submit(fetch_data_chunk, address, start_cursor, end_cursor))
            
        for future in as_completed(futures):
            all_fetched_ops.extend(future.result())
    
    duration = time.time() - start_time
    print(f"Fetched {len(all_fetched_ops)} operations in {duration:.2f} seconds.")

    # 3. Process results
    buckets_data = {
        "Unlocked": {"wallets": set(), "amount": 0.0},
        "2 Weeks": {"wallets": set(), "amount": 0.0},
        "6 Months": {"wallets": set(), "amount": 0.0},
        "1 Year": {"wallets": set(), "amount": 0.0},
        "3 Year": {"wallets": set(), "amount": 0.0}
    }
    
    total_amount = 0.0
    for op in all_fetched_ops:
        parsed = parse_operation(op)
        if parsed:
            bucket_name = get_bucket(parsed['duration'])
            if parsed['wallet']:
                buckets_data[bucket_name]['wallets'].add(parsed['wallet'])
            buckets_data[bucket_name]['amount'] += parsed['amount']
            total_amount += parsed['amount']

    # Calculate total unique participants across all buckets for percentage calculation
    total_wallets_sum = sum(len(data['wallets']) for data in buckets_data.values())

    # 4. Print summary
    print(f"\nSummary (Last {args.days} days):")
    print(f"{'Bucket':<15} | {'Wallets':<10} | {'Wallet %':<10} | {'Total Pi':<15} | {'Pi %'}")
    print("-" * 75)
    
    ordered_buckets = ["Unlocked", "2 Weeks", "6 Months", "1 Year", "3 Year"]
    for name in ordered_buckets:
        data = buckets_data[name]
        wallet_count = len(data['wallets'])
        amount = data['amount']
        
        wallet_pct = (wallet_count / total_wallets_sum * 100) if total_wallets_sum > 0 else 0
        pi_pct = (amount / total_amount * 100) if total_amount > 0 else 0
        
        print(f"{name:<15} | {wallet_count:<10} | {wallet_pct:>8.2f}% | {amount:<15.2f} | {pi_pct:>8.2f}%")

if __name__ == "__main__":
    main()
