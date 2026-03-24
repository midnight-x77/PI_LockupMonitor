import requests
import argparse
from datetime import datetime, timezone

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
        # Handle 'Z' suffix for ISO format strings
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
            # Set default wallet from the first claimant
            wallet = claimants[0].get('destination')
            
            # Loop through ALL claimants to find the lockup period ('not' block)
            for claimant in claimants:
                predicate = claimant.get('predicate', {})
                not_clause = predicate.get('not', {})
                if not_clause:
                    # Found the lockup! Update the wallet and extract info
                    wallet = claimant.get('destination')
                    
                    rel_before_val = not_clause.get('rel_before')
                    if rel_before_val is not None:
                        rel_before_sec = int(rel_before_val)
                    
                    if rel_before_sec is None:
                        abs_before_str = not_clause.get('abs_before')
                        if abs_before_str:
                            abs_before_ts = to_timestamp(abs_before_str)
                    
                    # Break once the 'not' block is found
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
        'abs_before': abs_before_ts,
        'rel_before': rel_before_sec,
        'duration': duration,
        'wallet': wallet
    }

def fetch_data_for_days(wallet_address, days):
    """
    Fetches all operations for the wallet address in the specified number of days.
    Uses the Horizon API and handles pagination.
    """
    url = f"https://api.mainnet.minepi.com/accounts/{wallet_address}/operations?order=desc&limit=200"
    all_ops = []
    now_ts = datetime.now(timezone.utc).timestamp()
    cutoff_ts = now_ts - (days * DAY_SEC)

    while url:
        try:
            response = requests.get(url)
            response.raise_for_status()
            data = response.json()
            records = data.get('_embedded', {}).get('records', [])
            
            if not records:
                break
                
            for op in records:
                created_at_str = op.get('created_at')
                # Reuse the timestamp conversion logic
                dt = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                created_at_ts = dt.timestamp()
                
                if created_at_ts < cutoff_ts:
                    return all_ops # Stop fetching as per specified time window
                
                all_ops.append(op)
            
            url = data.get('_links', {}).get('next', {}).get('href')
        except requests.exceptions.RequestException as e:
            print(f"Error fetching data: {e}")
            break
            
    return all_ops

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch Pi lockup statistics.")
    parser.add_argument("-d", "--days", type=int, default=1, help="Number of days to fetch data for (default: 1)")
    args = parser.parse_args()

    address = "GABT7EMPGNCQSZM22DIYC4FNKHUVJTXITUF6Y5HNIWPU4GA7BHT4GC5G"
    print(f"Fetching data for the last {args.days} day(s) for Pi lockup account: {address}")
    
    ops = fetch_data_for_days(address, args.days)
    
    buckets_data = {
        "Unlocked": {"wallets": set(), "amount": 0.0},
        "2 Weeks": {"wallets": set(), "amount": 0.0},
        "6 Months": {"wallets": set(), "amount": 0.0},
        "1 Year": {"wallets": set(), "amount": 0.0},
        "3 Year": {"wallets": set(), "amount": 0.0}
    }
    
    total_amount = 0.0
    
    for op in ops:
        parsed = parse_operation(op)
        if parsed:
            bucket_name = get_bucket(parsed['duration'])
            if parsed['wallet']:
                buckets_data[bucket_name]['wallets'].add(parsed['wallet'])
            buckets_data[bucket_name]['amount'] += parsed['amount']
            total_amount += parsed['amount']

    print(f"\nSummary (Last {args.days} days):")
    print(f"{'Bucket':<15} | {'Wallets':<10} | {'Total Pi':<15} | {'% of Total'}")
    print("-" * 60)
    
    ordered_buckets = ["Unlocked", "2 Weeks", "6 Months", "1 Year", "3 Year"]
    
    for name in ordered_buckets:
        data = buckets_data[name]
        wallet_count = len(data['wallets'])
        amount = data['amount']
        pct = (amount / total_amount * 100) if total_amount > 0 else 0
        print(f"{name:<15} | {wallet_count:<10} | {amount:<15.2f} | {pct:>10.2f}%")
