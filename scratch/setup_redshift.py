import os
import redshift_connector
from dotenv import load_dotenv

load_dotenv()

def run_setup():
    print("Connecting to Redshift...")
    try:
        conn = redshift_connector.connect(
            host=os.getenv('REDSHIFT_HOST'),
            port=int(os.getenv('REDSHIFT_PORT', '5439')),
            database=os.getenv('REDSHIFT_DB'),
            user=os.getenv('REDSHIFT_USER'),
            password=os.getenv('REDSHIFT_PASSWORD')
        )
        conn.autocommit = True
        cursor = conn.cursor()
        
        print("Creating Schema 'clm_soa'...")
        cursor.execute("CREATE SCHEMA IF NOT EXISTS clm_soa;")
        
        print("Creating Materialized View: mv_crv_data...")
        cursor.execute("""
            CREATE MATERIALIZED VIEW clm_soa.mv_crv_data AS
            SELECT event_type, value_recorded_date, principal_amount, repayment_type, 
                   interest_rate, slab_rate, lms_id, unposted_interest, 
                   transit_cashback, transit_paid_amount, status
            FROM dw.account_svc_customer_rupeek_view WHERE status = 'VALID';
        """)
        
        print("Creating Materialized View: mv_charges...")
        cursor.execute("""
            CREATE MATERIALIZED VIEW clm_soa.mv_charges AS
            SELECT lms_id, type, (value + COALESCE(tax, 0)) as total_charge, value_recorded_date
            FROM dw.account_svc_charges;
        """)
        
        print("Creating Materialized View: mv_customer_details...")
        cursor.execute("""
            CREATE MATERIALIZED VIEW clm_soa.mv_customer_details AS
            SELECT 'federal' as bank, loan_account_number as account_number, branchname as branch_name, 
                   borrower_name as customer_name, scheme_name, primary_mobile_number_decrypted as mobile_number
            FROM tech.mis_fed_outstanding_till_date
            UNION ALL
            SELECT 'sib' as bank, REPLACE(REPLACE(loanacno,'="',''),'"','') as account_number, branchname as branch_name, 
                   customername as customer_name, product_variant as scheme_name, 
                   REPLACE(REPLACE(mobilenumber_decrypted,'="',''),'"','') as mobile_number
            FROM tech.sib_mis_full;
        """)
        
        print("Creating Materialized View: mv_clm_loan_mapping...")
        cursor.execute("""
            CREATE MATERIALIZED VIEW clm_soa.mv_clm_loan_mapping AS
            SELECT l1.lms_id, l1.status, l1.los_id, l2.lms_id AS rcpl_loan_account, l1.branch_name, l1.type as loan_type,
                   CAST((COALESCE(l1.principal_amount,0) + COALESCE(l2.principal_amount,0)) AS DECIMAL(18,2)) AS total_loan_amount,
                   l1.sanction_date AS loan_start_date, l1.closure_date AS loan_end_date
            FROM dw.account_svc_loan l1
            LEFT JOIN dw.account_svc_loan l2 ON l1.support_lms_id = l2.lms_id;
        """)
        
        print("Creating Materialized View: mv_customer_profile...")
        cursor.execute("""
            CREATE MATERIALIZED VIEW clm_soa.mv_customer_profile AS
            SELECT m.gl, c.customerproofname, c.permanentaddress, c.city, c.street, c.locality, u.email, u.phone_decrypted
            FROM temp.mapping m
            JOIN dw.core_customerprofile c ON c.userid = m.requesterid
            LEFT JOIN dw.core_user u ON c.userid = u.id;
        """)
        
        print("Creating Materialized View: mv_gold_reg...")
        cursor.execute("""
            CREATE MATERIALIZED VIEW clm_soa.mv_gold_reg AS
            SELECT l.lms_id, g.gl_no, g.cldate, REGEXP_SUBSTR(g.scheme_code, '.*[0-9]+M') AS scheme_short
            FROM dw.account_svc_loan l
            JOIN dw.lms_t_gold_reg g ON g.gl_no = l.support_lms_id;
        """)
        
        print("Setup complete!")
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f"Error during setup: {e}")

if __name__ == "__main__":
    run_setup()
