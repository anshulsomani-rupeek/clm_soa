import os
import redshift_connector
from flask import Flask, render_template, request, jsonify
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# ── Database Connection ──────────────────────────────────────────────────────
def get_redshift_conn():
    return redshift_connector.connect(
        host=os.getenv('REDSHIFT_HOST'),
        port=int(os.getenv('REDSHIFT_PORT', '5439')),
        database=os.getenv('REDSHIFT_DB'),
        user=os.getenv('REDSHIFT_USER'),
        password=os.getenv('REDSHIFT_PASSWORD')
    )

# ── Query Functions ──────────────────────────────────────────────────────────
def query_crv_data(conn, lms_id):
    """Query dw.account_svc_customer_rupeek_view for MIS and DAY_CHANGE data."""
    query = """
    SELECT
        event_type,
        value_recorded_date,
        principal_amount,
        repayment_type,
        interest_rate,
        slab_rate,
        lms_id,
        unposted_interest,
        transit_cashback,
        transit_paid_amount
    FROM dw.account_svc_customer_rupeek_view
    WHERE lms_id = %s
      AND status = 'VALID'
    ORDER BY value_recorded_date,
             CASE event_type
               WHEN 'MIS' THEN 0
               WHEN 'DAY_CHANGE' THEN 1
               ELSE 2
             END
    """
    cursor = conn.cursor()
    cursor.execute(query, (lms_id,))
    rows = cursor.fetchall()
    cursor.close()

    # Convert to list of dicts
    result = []
    for row in rows:
        result.append({
            'event_type': row[0],
            'value_recorded_date': str(row[1])[:10],
            'principal_amount': float(row[2]) if row[2] else 0,
            'repayment_type': str(row[3]) if row[3] else '',
            'interest_rate': float(row[4]) if row[4] else 0,
            'slab_rate': float(row[5]) if row[5] else 0,
            'lms_id': str(row[6]) if row[6] else lms_id,
            'unposted_interest': float(row[7]) if row[7] else 0,
            'transit_cashback': float(row[8]) if row[8] else 0,
            'transit_paid_amount': float(row[9]) if row[9] else 0
        })
    return result

def query_charges(conn, lms_id):
    """Query dw.account_svc_charges for charges."""
    query = """
    SELECT
        type,
        SUM(value + COALESCE(tax, 0)) as total_charge,
        MAX(value_recorded_date) as charge_date
    FROM dw.account_svc_charges
    WHERE lms_id = %s
    GROUP BY type
    ORDER BY charge_date
    """
    cursor = conn.cursor()
    cursor.execute(query, (lms_id,))
    rows = cursor.fetchall()
    cursor.close()

    result = []
    for row in rows:
        result.append({
            'charge_type': row[0] or 'Charge',
            'total_charge': float(row[1]) if row[1] else 0,
            'charge_date': str(row[2])[:10] if row[2] else None
        })
    return result

def query_customer_details(conn, lms_id, bank='federal'):
    """Query tech.mis_fed_outstanding_till_date for customer and branch details."""
    if bank == 'sib':
        query = """
        SELECT DISTINCT 
            REPLACE(REPLACE(loanacno,'="',''),'"','') AS loanacno,
            sol_id,
            customername as borrower_name,
            branchname as branchname,
            REPLACE(REPLACE(mobilenumber_decrypted,'="',''),'"','') AS mobilenumber,
            product_variant
        FROM tech.sib_mis_full
        WHERE REPLACE(REPLACE(loanacno,'="',''),'"','') = %s
        LIMIT 1
        """
    else:
        query = """
        SELECT DISTINCT
            loan_account_number,
            branchname,
            borrower_name,
            scheme_name,
            primary_mobile_number_decrypted
        FROM tech.mis_fed_outstanding_till_date
        WHERE loan_account_number = %s
        LIMIT 1
        """

    cursor = conn.cursor()
    cursor.execute(query, (lms_id,))
    row = cursor.fetchone()
    cursor.close()

    if row:
        if bank == 'sib':
            return {
                'account_number': str(row[0]) if row[0] else lms_id,
                'branch_name': row[3] or '',
                'customer_name': row[2] or '',
                'scheme_name': row[5] or '',
                'mobile_number': row[4] or ''
            }
        else:
            return {
                'account_number': str(row[0]) if row[0] else lms_id,
                'branch_name': row[1] or '',
                'customer_name': row[2] or '',
                'scheme_name': row[3] or '',
                'mobile_number': row[4] or ''
            }
    return {
        'account_number': lms_id,
        'branch_name': '',
        'customer_name': '',
        'scheme_name': '',
        'mobile_number': ''
    }

def query_sib_clm_mapping(conn, lms_id):
    """Query mapping for SIB CLM loans."""
    query = """
    WITH lender_map AS (
        SELECT '62be94b2beb2db743c17bc4c' AS core_id, 'Axis' AS lender_name, 'axis' AS slug, 'AXIS' AS gold_benchmark UNION ALL
        SELECT '5a43cfbebc40a39a3bc1207d', 'Federal Bank Limited', 'federal', 'IBJA' UNION ALL
        SELECT '5d75924e5bf87df5130767ae', 'ICICI Bank', 'icici-bank', 'ICICI' UNION ALL
        SELECT '635a0b977762f40fc068fe03', 'Indian Bank', 'indianbank', 'INDIANBANK' UNION ALL
        SELECT '5cdd3ebad54a11e613c3a6b5', 'Karur Vysya Bank', 'kvb', 'KVB' UNION ALL
        SELECT '5f916dab9617a826bd84a9f3', 'Kisetsu Saison Finance India Private Limited', 'saison', 'AGLOC' UNION ALL
        SELECT '637de2591a0aab715655885b', 'NDX P2P Private Limited', 'liquiloans', 'AGLOC' UNION ALL
        SELECT '5ac38436aa1a12f3691dbf99', 'Rupeek Capital Private Limited', 'rupeek', 'AGLOC' UNION ALL
        SELECT '60b7f0e0cbe7401f71ffcbda', 'South Indian Bank', 'sib', 'IBJA' UNION ALL
        SELECT '57288d5c3e2291476b2a0a4e', 'Yogakshemam Loans Limited', 'yog', 'AGLOC' UNION ALL
        SELECT '63e340d634c9599729eb97d7', 'Cholamandalam Investment and Finance Company Limited', 'cholamandalam', 'AGLOC'
    )
    SELECT 
        l1.status,
        l1.los_id,
        l2.lms_id AS rcpl_loan_account,
        CAST((COALESCE(l1.principal_amount,0) + COALESCE(l2.principal_amount,0)) AS DECIMAL(18,2)) AS total_loan_amount,
        l1.sanction_date AS loan_start_date,
        l1.closure_date AS loan_end_date,
        l1.type as loan_type,
        l1.branch_name
    FROM dw.account_svc_loan l1
    LEFT JOIN dw.account_svc_loan l2 ON l1.support_lms_id = l2.lms_id
    LEFT JOIN lender_map lm1 ON l1.lender_id = lm1.core_id
    WHERE l1.lms_id = %s
    """
    cursor = conn.cursor()
    cursor.execute(query, (lms_id,))
    row = cursor.fetchone()
    cursor.close()
    if row:
        return {
            'status': row[0],
            'los_id': row[1],
            'rcpl_loan_account': row[2],
            'total_loan_amount': float(row[3]) if row[3] else 0,
            'loan_start_date': str(row[4])[:10] if row[4] else None,
            'loan_end_date': str(row[5])[:10] if row[5] else None,
            'loan_type': row[6],
            'branch_name': row[7]
        }
    return None

def query_sib_customer_address(conn, lms_id):
    """Attempt to find SIB customer address and city."""
    query = """
    SELECT cp.permanentaddress, cp.city, cp.street, cp.locality
    FROM dw.core_customerprofile cp
    JOIN dw.account_svc_loan l ON cp.userid = l.id  -- This is a guess, let's try it
    WHERE l.lms_id = %s
    LIMIT 1
    """
    # Note: The mapping between core_customerprofile and account_svc_loan 
    # might vary. If this fails, we return empty.
    try:
        cursor = conn.cursor()
        cursor.execute(query, (lms_id,))
        row = cursor.fetchone()
        cursor.close()
        if row:
            return {
                'address': row[0] or f"{row[2] or ''} {row[3] or ''}".strip(),
                'city': row[1] or ''
            }
    except:
        pass
    return {'address': '', 'city': ''}

def query_scheme_short(conn, lms_id):
    """Fetch scheme short code for the loan."""
    query = """
    SELECT 
        REGEXP_SUBSTR(scheme_code, '.*[0-9]+M') AS scheme_short
    FROM dw.lms_t_gold_reg 
    WHERE gl_no IN (
       SELECT support_lms_id FROM dw.account_svc_loan
       WHERE lms_id = %s
    )
    LIMIT 1
    """
    try:
        cursor = conn.cursor()
        cursor.execute(query, (lms_id,))
        row = cursor.fetchone()
        cursor.close()
        if row:
            return row[0]
    except:
        pass
    return None

def query_sib_gold_dates(conn, lms_id):
    """Fetch loan end date (cldate) from dw.lms_t_gold_reg via support_lms_id."""
    query = """
    SELECT gl_no, cldate
    FROM dw.lms_t_gold_reg
    WHERE gl_no IN (
        SELECT support_lms_id FROM dw.account_svc_loan
        WHERE lms_id = %s
    )
    LIMIT 1
    """
    try:
        cursor = conn.cursor()
        cursor.execute(query, (lms_id,))
        row = cursor.fetchone()
        cursor.close()
        if row:
            return {
                'gl_no': str(row[0]) if row[0] else None,
                'cldate': str(row[1])[:10] if row[1] else None
            }
    except Exception as e:
        print(f"[gold_dates] Error: {e}")
    return {'gl_no': None, 'cldate': None}

def query_sib_customer_profile(conn, lms_id):
    """Fetch profile data using temp.mapping table for SIB loans."""
    query = """
    SELECT  
        c.customerproofname,
        c.permanentaddress,
        u.email,
        u.phone_decrypted
    FROM dw.core_customerprofile c
    LEFT JOIN dw.core_user u
        ON c.userid = u.id
    WHERE c.userid IN (SELECT DISTINCT requesterid FROM temp.mapping WHERE gl = %s)
    LIMIT 1
    """
    try:
        cursor = conn.cursor()
        cursor.execute(query, (lms_id,))
        row = cursor.fetchone()
        cursor.close()
        print(f"[profile] lms_id={lms_id} row={row}")
        if row:
            return {
                'customer_name': row[0],
                'permanent_address': row[1],
                'email': row[2],
                'mobile_number': row[3]
            }
    except Exception as e:
        print(f"[profile] ERROR: {e}")
    return {'customer_name': '', 'permanent_address': '', 'email': '', 'mobile_number': ''}


# ── SOA Calculation Logic ────────────────────────────────────────────────────
def build_soa(data, bank='federal', status='closed'):
    """
    Port of buildDashboard() from main.html.
    Calculates Statement of Account with interest accrual, repayments, rebates, and charges.
    """
    ORDER = {'MIS': 0, 'DAY_CHANGE': 1, 'REPAYMENT': 2}

    # Sort by date, then by event type
    data.sort(key=lambda x: (
        x['value_recorded_date'],
        ORDER.get(x.get('event_type'), 3)
    ))

    # Extract MIS record (first occurrence)
    mis = next((r for r in data if r.get('event_type') == 'MIS'), None)
    lms_id = mis['lms_id'] if mis else (data[0]['lms_id'] if data else '—')
    interest_rate = mis['interest_rate'] if mis else '—'
    slab_rate = mis['slab_rate'] if mis else '—'
    disbursed = mis['principal_amount'] if mis else 0
    disb_date = mis['value_recorded_date'] if mis else '—'

    day_changes = [r for r in data if r.get('event_type') == 'DAY_CHANGE']
    repayments = [r for r in data if r.get('event_type') == 'REPAYMENT']

    # Find all repayment dates
    all_rep_dates = sorted(set(r['value_recorded_date'] for r in repayments))
    last_rep_date = all_rep_dates[-1] if all_rep_dates else None
    last_rep_mo = last_rep_date[:7] if last_rep_date else None

    # Index repayments and day changes by date
    rep_by_date = {}
    for r in repayments:
        if r['value_recorded_date'] not in rep_by_date:
            rep_by_date[r['value_recorded_date']] = []
        rep_by_date[r['value_recorded_date']].append(r)

    dc_by_date = {}
    dc_by_month = {}
    for r in day_changes:
        mo = r['value_recorded_date'][:7]
        if r['value_recorded_date'] not in dc_by_date:
            dc_by_date[r['value_recorded_date']] = []
        dc_by_date[r['value_recorded_date']].append(r)
        if mo not in dc_by_month:
            dc_by_month[mo] = []
        dc_by_month[mo].append(r)

    # Get all months from day changes and closing month
    all_months = sorted(set(
        list(dc_by_month.keys()) + ([last_rep_mo] if last_rep_mo else [])
    ))

    # Calculate interest entries per month
    interest_entries = []
    for mo in all_months:
        # Only treat as closing if the loan is actually closed/closing in the data
        is_closing = (mo == last_rep_mo and status.lower() not in ['open', 'opened', 'active'])
        recs = sorted(
            dc_by_month.get(mo, []),
            key=lambda x: x['value_recorded_date']
        )

        interest = 0
        post_date = None
        end_date = None

        if is_closing:
            dcs_on_rep = sorted(
                dc_by_date.get(last_rep_date, []),
                key=lambda x: x['value_recorded_date']
            )
            dc_rec = dcs_on_rep[-1] if dcs_on_rep else None
            
            reps_on_last_date = rep_by_date.get(last_rep_date, [])
            rep_rec = next((r for r in reps_on_last_date if r.get('unposted_interest', 0) > 0), None)

            is_repledge = any('repledge' in (r.get('repayment_type') or '').lower() for r in reps_on_last_date)

            if is_repledge:
                interest = 0
            else:
                interest = (dc_rec['unposted_interest'] if dc_rec and dc_rec.get('unposted_interest', 0) > 0
                           else (rep_rec['unposted_interest'] if rep_rec else 0))

            post_date = last_rep_date
            end_date = last_rep_date
        else:
            rec = recs[-1] if recs else None
            if not rec:
                continue
            interest = rec.get('unposted_interest', 0)
            end_date = rec['value_recorded_date']
            # Next day
            d = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
            post_date = d.strftime('%Y-%m-%d')

        if interest > 0:
            if bank == 'sib' and post_date >= '2026-02-01' and not is_closing:
                # Calculate one day interest as difference between last two days of the month
                one_day_int = 0
                if len(recs) >= 2:
                    one_day_int = recs[-1].get('unposted_interest', 0) - recs[-2].get('unposted_interest', 0)
                interest += one_day_int

            interest_entries.append({
                'mo': mo,
                'post_date': post_date,
                'end_date': end_date,
                'interest': interest
            })

    # Build transaction rows
    balance = 0
    rows = []

    # 1. Disbursement
    if mis:
        balance -= mis['principal_amount']
        rows.append({
            'date': mis['value_recorded_date'],
            'narration': 'Loan Disbursement',
            'withdrawal': mis['principal_amount'],
            'deposit': 0,
            'balance': balance,
            'cr_dr': 'DR'
        })

    # 2. Interleave interest and repayment events
    events = []
    for e in interest_entries:
        events.append({'date': e['post_date'], 'type': 'interest', 'data': e})
    for d in all_rep_dates:
        events.append({'date': d, 'type': 'repayment', 'data': rep_by_date[d]})

    events.sort(key=lambda x: (x['date'], 0 if x['type'] == 'interest' else 1))

    for ev in events:
        if ev['type'] == 'interest':
            e = ev['data']
            balance -= e['interest']
            # For the first interest entry, use disbursement date if it matches the month
            start_date_raw = f"{e['mo']}-01"
            if mis and mis['value_recorded_date'][:7] == e['mo']:
                start_date_raw = mis['value_recorded_date']
            
            # Format the dates in the narration to DD-MM-YYYY
            start_date_fmt = _format_date(start_date_raw)
            end_date_fmt = _format_date(e['end_date'])

            rows.append({
                'date': e['post_date'],
                'narration': f"Interest Accrual ({start_date_fmt} to {end_date_fmt})",
                'withdrawal': e['interest'],
                'deposit': 0,
                'balance': balance,
                'cr_dr': 'DR'
            })
        else:
            for rep in ev['data']:
                # Rebate
                if rep.get('transit_cashback', 0) > 0:
                    balance += rep['transit_cashback']
                    rows.append({
                        'date': rep['value_recorded_date'],
                        'narration': 'Rebate',
                        'withdrawal': 0,
                        'deposit': rep['transit_cashback'],
                        'balance': balance,
                        'cr_dr': 'CR'
                    })
                # Repayment
                if rep.get('transit_paid_amount', 0) > 0:
                    balance += rep['transit_paid_amount']
                    rows.append({
                        'date': rep['value_recorded_date'],
                        'narration': f"Repayment ({rep.get('repayment_type', '')})",
                        'withdrawal': 0,
                        'deposit': rep['transit_paid_amount'],
                        'balance': balance,
                        'cr_dr': 'CR'
                    })

    # Calculate summary
    total_withdrawals = sum(r['withdrawal'] for r in rows)
    total_deposits = sum(r['deposit'] for r in rows)
    total_interest = sum(r['withdrawal'] for r in rows if 'Interest Accrual' in r['narration'])
    total_repayment = sum(r['deposit'] for r in rows if r['narration'] == 'Repayment')
    total_rebate = sum(r['deposit'] for r in rows if r['narration'] == 'Rebate')
    closing_balance = balance
    last_date = repayments[-1]['value_recorded_date'] if repayments else '—'

    return {
        'rows': rows,
        'meta': {
            'lms_id': lms_id,
            'customer_name': '',
            'interest_rate': interest_rate,
            'slab_rate': slab_rate,
            'disbursed': disbursed,
            'disb_date': disb_date,
            'last_date': last_date,
            'total_withdrawals': total_withdrawals,
            'total_deposits': total_deposits,
            'total_interest': total_interest,
            'total_repayment': total_repayment,
            'total_rebate': total_rebate,
            'closing_balance': closing_balance
        }
    }

# ── Routes ───────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate', methods=['POST'])
def generate():
    lms_id = request.form.get('lms_id', '').strip()
    bank = request.form.get('bank', 'federal').strip().lower()

    if not lms_id:
        return jsonify({'error': 'LMS ID is required'}), 400

    try:
        conn = get_redshift_conn()

        # Query data
        crv_data = query_crv_data(conn, lms_id)
        charges = query_charges(conn, lms_id)
        customer = query_customer_details(conn, lms_id, bank)
        if customer:
            if customer.get('customer_name'):
                customer['customer_name'] = customer['customer_name'].title()
            if customer.get('branch_name'):
                customer['branch_name'] = customer['branch_name'].title()

        clm_data = None
        if bank == 'sib':
            clm_data = query_sib_clm_mapping(conn, lms_id)
            addr_data = query_sib_customer_address(conn, lms_id)
            profile_data = query_sib_customer_profile(conn, lms_id)
            scheme_short = query_scheme_short(conn, lms_id)
            gold_dates = query_sib_gold_dates(conn, lms_id)
            if clm_data:
                # Update customer details with CLM data if found
                customer['status'] = clm_data['status']
                customer['loan_start_date'] = clm_data['loan_start_date']
                customer['loan_end_date'] = clm_data['loan_end_date']
                customer['los_id'] = clm_data['los_id']
                customer['rcpl_loan_account'] = clm_data['rcpl_loan_account']
                customer['total_loan_amount'] = clm_data['total_loan_amount']
                customer['address'] = addr_data['address']
                customer['city'] = addr_data['city']
                if profile_data.get('customer_name'):
                    customer['customer_name'] = profile_data['customer_name'].title()
                if profile_data.get('mobile_number'):
                    customer['mobilenumber'] = profile_data['mobile_number']
                customer['permanent_address'] = profile_data.get('permanent_address', '').title()
                customer['email'] = profile_data.get('email', '')
                if not customer.get('branch_name') and clm_data['branch_name']:
                    customer['branch_name'] = clm_data['branch_name'].title()
                elif customer.get('branch_name'):
                     customer['branch_name'] = customer['branch_name'].title()
                customer['scheme_short'] = scheme_short or ''
                customer['gold_loan_start'] = gold_dates.get('gl_no')
                customer['gold_loan_end'] = gold_dates.get('cldate')

            # SIB Specific Logic: If loan is OPEN/OPENED, restrict SOA till the first day of the current month
            if clm_data and clm_data['status'].lower() in ['open', 'opened', 'active']:
                first_day_of_month = datetime.now().replace(day=1).strftime('%Y-%m-%d')
                crv_data = [r for r in crv_data if r['value_recorded_date'] <= first_day_of_month]
                charges = [r for r in charges if r['charge_date'] and r['charge_date'] <= first_day_of_month]
                # Update meta last_date to match the cut-off
                if crv_data:
                    # Sort to find last date
                    temp_sorted = sorted(crv_data, key=lambda x: x['value_recorded_date'])
                    meta_last_date = temp_sorted[-1]['value_recorded_date']
                else:
                    meta_last_date = first_day_of_month
                
                # We need to manually inject this into the context later
                customer['custom_closing_date'] = meta_last_date

        conn.close()

        # Calculate SOA
        soa_result = build_soa(crv_data, bank=bank, status=customer.get('status', 'closed'))
        transactions = soa_result['rows']   # raw YYYY-MM-DD dates still intact
        meta = soa_result['meta']

        total_service_fee = 0
        service_fee_date = '—'
        for charge in charges:
            if charge['total_charge'] > 0 and charge['charge_date']:
                c_type = (charge['charge_type'] or '').upper()
                if 'SERVICE_FEE' in c_type or 'SERVICE FEE' in c_type:
                    total_service_fee += charge['total_charge']
                    service_fee_date = charge['charge_date']
                elif 'PF' in c_type or 'PROCESSING' in c_type or 'UPFRONT' in c_type:
                    # DR entry for the UPFRONT PF / Processing Fee at its actual date
                    transactions.append({
                        'date': charge['charge_date'],
                        'narration': f"{charge['charge_type']} Charge",
                        'withdrawal': charge['total_charge'],
                        'deposit': 0,
                        'balance': 0,
                        'cr_dr': 'DR'
                    })

        # Add Service Fee entries at the closing date (DR and CR of same value)
        # Only for CLOSED loans
        is_open = customer.get('status', '').lower() in ['open', 'opened', 'active']
        if total_service_fee > 0 and not is_open:
            closing_date = meta['last_date']
            # DR entry
            transactions.append({
                'date': closing_date,
                'narration': 'Service Fee Charge',
                'withdrawal': total_service_fee,
                'deposit': 0,
                'balance': 0,
                'cr_dr': 'DR'
            })
            # CR entry
            transactions.append({
                'date': closing_date,
                'narration': 'Service Fee Paid',
                'withdrawal': 0,
                'deposit': total_service_fee,
                'balance': 0,
                'cr_dr': 'CR'
            })

        # Sort all rows by raw date so charges slot into the right position
        transactions.sort(key=lambda x: x['date'])

        # Recalculate running balance from scratch over the merged list
        running = 0
        total_w = 0
        total_d = 0
        for txn in transactions:
            if txn['withdrawal'] > 0:
                running -= txn['withdrawal']
                total_w += txn['withdrawal']
            if txn['deposit'] > 0:
                running += txn['deposit']
                total_d += txn['deposit']
            txn['balance'] = running

        is_closed = customer.get('status', '').lower() == 'closed'

        # Update grand totals to include charges
        meta['total_withdrawals'] = total_w
        meta['total_deposits'] = total_d

        # Format transaction dates to DD-MM-YYYY (only after sorting & balance calc)
        for txn in transactions:
            txn['date'] = _format_date(txn['date'])

        # Populate City Name from Branch Name if empty
        if not customer.get('city') and customer.get('branch_name'):
            # e.g., "City Branch, Bangalore" -> "Bangalore"
            if ',' in customer['branch_name']:
                customer['city'] = customer['branch_name'].split(',')[-1].strip()

        # Prepare template context
        context = {
            'customer_name': customer['customer_name'] or meta['customer_name'],
            'account_no': customer['account_number'],
            'branch_name': customer['branch_name'],
            'scheme_name': customer['scheme_name'],
            'mobile_number': customer['mobile_number'],
            'opening_date': _format_date(meta['disb_date']),
            'closing_date': _format_date(customer.get('custom_closing_date', meta['last_date'])),
            'transactions': transactions,
            'total_withdrawals': meta['total_withdrawals'],
            'total_deposits': meta['total_deposits'],
            'lms_id': meta['lms_id'],
            'bank': bank,
            'service_fee_amount': total_service_fee,
            'service_fee_date': _format_date(service_fee_date),
            'status': customer.get('status', '—'),
            'address': customer.get('address', '—'),
            'city': customer.get('city', '—'),
            'loan_start_date': _format_date(customer.get('loan_start_date')),
            'loan_end_date': _format_date(customer.get('loan_end_date')),
            'los_id': customer.get('los_id', '—'),
            'rcpl_loan_account': customer.get('rcpl_loan_account', '—'),
            'total_loan_amount': customer.get('total_loan_amount', 0),
            'permanent_address': customer.get('permanent_address', ''),
            'email': customer.get('email', ''),
            'scheme_short': customer.get('scheme_short', ''),
            'gold_loan_start': _format_date(customer.get('gold_loan_start')),
            'gold_loan_end': _format_date(customer.get('gold_loan_end'))
        }

        return render_template('soa.html', **context)

    except Exception as e:
        return jsonify({'error': str(e)}), 500

def _format_date(date_str):
    """Convert YYYY-MM-DD to DD-MM-YYYY."""
    if date_str == '—' or not date_str:
        return '—'
    try:
        d = datetime.strptime(date_str, '%Y-%m-%d')
        return d.strftime('%d-%m-%Y')
    except:
        return date_str

if __name__ == '__main__':
    # Use the port assigned by the hosting provider or default to 8080
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
