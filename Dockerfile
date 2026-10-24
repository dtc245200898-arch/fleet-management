# Sử dụng môi trường Node.js bản nhẹ
FROM node:18-alpine

# Tạo thư mục làm việc trong container
WORKDIR /app

# Copy package.json và cài đặt thư viện
COPY package*.json ./
RUN npm install

# Copy toàn bộ mã nguồn vào container
COPY . .

# Mở port 3000
EXPOSE 3000

# Lệnh chạy ứng dụng
CMD ["npm", "start"]