import pkg from 'pg';
const { Pool } = pkg;

const pool = new Pool({
  connectionString: process.env.DATABASE_URL || 'postgres://crm:crm_password@localhost:5432/crmdb'
});

export default pool;
