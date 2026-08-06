# AI Diff Review Service

An AI diff review service that implements the contract exactly — clients POST a unified diff, the service reviews it asynchronously, and returns structured findings.

## How to Deploy

1. Copy `compose.yaml`
2. Create a `.env` file using the format shown in `example.env`
3. Run:
   ```bash
   docker-compose up -d
   ```

## API Usage

| Method | Endpoint | Auth |
|--------|----------|------|
| GET | `/health` | public |
| GET | `/spec` | public |
| POST | `/v1/reviews` | required |
| GET | `/v1/reviews/{jobId}` | required |
| GET | `/v1/reviews/{jobId}/stream` | required (SSE) |

## Architecture

See [`SUBMISSION.md`](./SUBMISSION.md) for architecture, provider design, and verification details.
