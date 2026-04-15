FROM node:22-alpine

WORKDIR /repo

COPY package.json /repo/package.json
COPY apps/web/package.json /repo/apps/web/package.json
COPY packages/shared-types/package.json /repo/packages/shared-types/package.json
COPY packages/shared-ui/package.json /repo/packages/shared-ui/package.json
COPY packages/config/package.json /repo/packages/config/package.json

RUN npm install

COPY apps/web /repo/apps/web
COPY packages /repo/packages

EXPOSE 3000

CMD ["npm", "run", "dev", "--workspace", "@platform/web", "--", "--hostname", "0.0.0.0", "--port", "3000"]
