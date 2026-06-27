const { Client } = require('pg');
const bcrypt = require('bcryptjs');

(async () => {
  const client = new Client({ connectionString: process.env.DATABASE_URL });
  await client.connect();

  const email = process.env.ADMIN_EMAIL || 'admin@moon-sun.cz';
  const password = process.env.ADMIN_PASSWORD || 'ChangeMe123!';
  const hashed = await bcrypt.hash(password, 10);

  const result = await client.query('SELECT id FROM users WHERE email=$1', [email]);
  if (result.rowCount === 0) {
    await client.query('INSERT INTO users (email, password_hash, full_name, role) VALUES ($1, $2, $3, $4)', [email, hashed, 'Admin', 'admin']);
    console.log('admin user created:', email);
  } else {
    console.log('admin exists');
  }

  await client.end();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
