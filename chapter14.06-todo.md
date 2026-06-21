# Open TODOs: Recipe 14.6: Patient Flow and Bed Assignment

> Auto-extracted 2026-06-18 from inline source comments (6 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## architecture — `chapter14.06-architecture.md`

- **L13** — TODO (TechWriter): Expert review A2 (MEDIUM). Add note on configuring a DLQ (SQS) on the Lambda event source mapping for Kinesis processing failures. A lost ADT event means state model diverges from reality. Alarm on DLQ depth and investigate immediately.
- **L14** — TODO (TechWriter): Expert review A4 (LOW). Add brief shard count guidance: single shard sufficient for most single-hospital deployments (up to ~3,600 events/hour); partition by facility ID for multi-campus.
- **L20** — TODO (TechWriter): Expert review A1 (HIGH). Add note specifying ElastiCache Redis with Multi-AZ replication as minimum production config. Add graceful degradation strategy: if Redis unavailable, fall back to periodic EventBridge schedule; if in-flight state unreadable, treat all beds as potentially available and flag recommendations with lower confidence.
- **L93** — TODO (TechWriter): Expert review N1 (MEDIUM). Add VPC endpoint list to prerequisites: DynamoDB (gateway), S3 (gateway), Kinesis (interface), Step Functions (interface), EventBridge (interface), CloudWatch Logs (interface), execute-api (interface), KMS (interface). Budget ~$50-60/month for interface endpoints in 3-AZ deployment.
- **L94** — TODO (TechWriter): Expert review N2 (MEDIUM). Add paragraph in State Ingestion or prerequisites on EHR integration network path: Direct Connect + VPN backup for on-premises EHR; VPC peering/PrivateLink for cloud-hosted EHR; monitor connection health; surface stale-state warning if ADT feed down >5 minutes.
- **L445** — TODO (TechWriter): Add "Why This Isn't Production-Ready" section between Expected Results and Variations per RECIPE-GUIDE. Content could expand on the "Where It Struggles" bullets above plus production gaps like formal validation testing, integration certification with specific EHR vendors, and clinical safety review processes.
