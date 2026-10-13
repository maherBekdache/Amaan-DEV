FROM node:22-alpine
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund
COPY src ./src
# /data holds only the WhatsApp login session and the chat selection.
ENV WA_AUTH_DIR=/data HOST=0.0.0.0 PORT=8090 NODE_ENV=production
RUN mkdir -p /data && chown node:node /data
USER node
EXPOSE 8090
CMD ["node", "src/index.js"]
