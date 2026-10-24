const express = require('express');
const { Pool } = require('pg');

const app = express();
app.use(express.json());

// Kết nối PostgreSQL thông qua biến môi trường từ Docker
const pool = new Pool({
  user: process.env.DB_USER || 'admin',
  host: process.env.DB_HOST || 'localhost',
  database: process.env.DB_NAME || 'fleet_db',
  password: process.env.DB_PASSWORD || '123456',
  port: 5432,
});

// Tự động tạo bảng nếu chưa có
pool.query(`
  CREATE TABLE IF NOT EXISTS vehicles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100),
    license_plate VARCHAR(50),
    status VARCHAR(50)
  )
`).catch(err => console.error('Lỗi tạo bảng:', err));

// API: Lấy danh sách xe
app.get('/api/vehicles', async (req, res) => {
  try {
    const result = await pool.query('SELECT * FROM vehicles');
    res.json(result.rows);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// API: Thêm xe mới
app.post('/api/vehicles', async (req, res) => {
  const { name, license_plate, status } = req.body;
  try {
    const result = await pool.query(
      'INSERT INTO vehicles (name, license_plate, status) VALUES ($1, $2, $3) RETURNING *',
      [name, license_plate, status]
    );
    res.json(result.rows[0]);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Hệ thống quản lý đội xe đang chạy tại port ${PORT}`);
});