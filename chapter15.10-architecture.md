# Recipe 15.10 Architecture and Implementation: Hospital Resource Allocation Under Uncertainty

*Companion to [Recipe 15.10: Hospital Resource Allocation Under Uncertainty](chapter15.10-hospital-resource-allocation-uncertainty). This page covers the AWS architecture, services, and prerequisites. For the problem framing, conceptual approach, and pseudocode walkthrough, start with the main recipe.*

---

## The AWS Implementation

### Why These Services

**Amazon SageMaker for RL training.** SageMaker provides managed RL training with support for custom environments, multiple RL algorithms (through RLlib integration), and distributed training across multiple instances. For a complex hospital simulation environment, you need GPU instances for the policy network and CPU instances for running multiple simulator copies in parallel. SageMaker handles this orchestration.

**AWS Step Functions for the training pipeline.** The end-to-end flow (data extraction, simulator calibration, training, evaluation, model registration) is a multi-step workflow with conditional logic (only deploy if evaluation metrics exceed threshold). Step Functions orchestrates this cleanly with retry logic and error handling.

**Amazon Kinesis Data Streams for real-time state ingestion.** Hospital operational data arrives continuously from multiple source systems. Kinesis ingests ADT events, staffing updates, and equipment status changes in real-time, feeding the state aggregator that builds the current hospital state vector.

**Amazon DynamoDB for state storage and action logging.** Every state observation and every recommendation (accepted or rejected) gets logged. DynamoDB's single-digit-millisecond latency supports real-time inference while its durability supports audit requirements. The time-series nature of the data maps well to DynamoDB's sort key patterns.

**AWS Lambda for inference.** Once trained, the policy network is relatively small (a few hundred MB). Lambda can load the model and produce a recommendation in under a second given a state vector. For a decision support system that produces recommendations every 15-30 minutes, Lambda's per-invocation pricing is more economical than a persistent endpoint.

**Amazon S3 for training data and model artifacts.** Historical operational data, simulator configurations, training checkpoints, and final model artifacts all live in S3. Lifecycle policies manage the volume of training data over time.

### Architecture Diagram

```mermaid
flowchart TB
    subgraph Data Ingestion
        A[ADT System] -->|Events| K[Kinesis Data Stream]
        B[Staffing System] -->|Updates| K
        C[OR Scheduling] -->|Cases| K
        D[Equipment Tracking] -->|Status| K
    end

    K --> SA[Lambda: State Aggregator]
    SA --> DDB[DynamoDB: State Store]

    subgraph Training Pipeline
        S3H[S3: Historical Data] --> CAL[SageMaker Processing:\nSimulator Calibration]
        CAL --> SIM[Custom Gym Environment:\nHospital Simulator]
        SIM --> TRAIN[SageMaker RL Training:\nPPO + Constraints]
        TRAIN --> EVAL[SageMaker Processing:\nOffline Evaluation]
        EVAL -->|Pass| REG[SageMaker Model Registry]
    end

    subgraph Inference
        DDB -->|Current State| INF[Lambda: Policy Inference]
        REG -->|Model Artifact| INF
        INF --> CC[Constraint Checker]
        CC --> REC[Recommendations API]
    end

    REC --> UI[Capacity Dashboard]
    UI --> HUMAN[Bed Coordinator / Charge Nurse]

    SF[Step Functions] -.->|Orchestrates| CAL
    SF -.->|Orchestrates| TRAIN
    SF -.->|Orchestrates| EVAL
```

### Prerequisites

| Requirement | Details |
|-------------|---------|
| AWS Services | SageMaker, Step Functions, Kinesis, DynamoDB, Lambda, S3, API Gateway, CloudWatch |
| IAM Permissions | sagemaker:CreateTrainingJob, sagemaker:CreateModel, kinesis:GetRecords, dynamodb:PutItem/GetItem, lambda:InvokeFunction, s3:GetObject/PutObject, states:StartExecution |
| BAA | Required. All operational data contains patient identifiers (room assignments, acuity levels). |
| Encryption | S3 SSE-KMS, DynamoDB encryption at rest, Kinesis server-side encryption, Lambda environment variable encryption |
| VPC | Training and inference in private subnets. VPC endpoints for S3, DynamoDB, SageMaker. No public internet access for PHI-containing workloads. |
| CloudTrail | All API calls logged. DynamoDB streams for state change audit. |
| Sample Data | Synthetic hospital operational data for development. Real ADT feeds for calibration (data governance approval needed, and it takes longer than you think). |
| Cost Estimate | Training: ~$500-2,000 per training run (GPU instances for 8-24 hours). Inference: ~$50-200/month (Lambda invocations every 15-30 min). Data storage: ~$100-500/month. |

<!-- TODO (TechWriter): Expert review S1 (MEDIUM). IAM permissions list is incomplete. Add: kms:Decrypt and kms:GenerateDataKey (scoped to CMK ARN), kinesis:DescribeStream and kinesis:GetShardIterator, cloudwatch:PutMetricData, logs:CreateLogGroup and logs:PutLogEvents, sagemaker:DescribeTrainingJob, and API Gateway permissions. Note that all permissions should use resource-level ARN restrictions. -->
<!-- TODO (TechWriter): Expert review N1 (MEDIUM). VPC endpoint list is incomplete. Add endpoints for Kinesis Streams, Step Functions, CloudWatch, CloudWatch Logs, and API Gateway (or specify private API). Note that NAT Gateway is acceptable as fallback but VPC endpoints preferred for PHI workloads. -->

### Ingredients

| AWS Service | Role in This Recipe |
|-------------|-------------------|
| Amazon SageMaker | RL model training with custom hospital simulation environment |
| AWS Step Functions | Orchestration of training, evaluation, and deployment pipeline |
| Amazon Kinesis Data Streams | Real-time ingestion of hospital operational events |
| Amazon DynamoDB | State storage, action logging, and audit trail |
| AWS Lambda | State aggregation and policy inference |
| Amazon S3 | Training data, simulator configs, model artifacts |
| Amazon API Gateway | REST endpoint for recommendation requests |
| Amazon CloudWatch | Monitoring model performance and operational metrics |

---

<!-- TODO (TechWriter): RECIPE-GUIDE compliance gap. The architecture companion is missing "Pseudocode Walkthrough," "Expected Results," and "Why This Isn't Production-Ready" sections. These currently live in the main recipe file. A future pass should move them here per the three-file structure in RECIPE-GUIDE.md. -->

## Variations and Extensions

### 1. Multi-Hospital System Coordination

For health systems with multiple campuses, extend the state to include inter-facility transfer options. The action space includes "divert ambulance to campus B" and "transfer patient from campus A ICU to campus C step-down." This turns a single-agent problem into a multi-agent coordination problem. Start with a centralized policy that observes all campuses, then explore decentralized execution with communication.

### 2. Surge Capacity Planning (Pandemic Mode)

Add a "surge mode" to the simulation that models pandemic-scale demand increases. Train a separate policy (or a mode-conditional policy) for surge scenarios where normal operating procedures are suspended. This includes activating non-traditional spaces (conference rooms as patient areas), crisis staffing ratios, and equipment redeployment. The policy must recognize when to recommend activating surge protocols.

### 3. Predictive Pre-positioning

Rather than reacting to current state, use forecasting models (see Chapter 12 recipes on hospital census and ED arrival forecasting) to predict state 4-8 hours ahead. Feed predicted future state into the policy to enable proactive resource positioning. This is where RL and forecasting integrate: the forecast provides the "look-ahead" and the policy decides what to do about it.

---

## Additional Resources

### AWS Documentation

- [Amazon SageMaker RL Documentation](https://docs.aws.amazon.com/sagemaker/latest/dg/reinforcement-learning.html) - Setup and configuration for RL training jobs
- [SageMaker Custom Environments](https://docs.aws.amazon.com/sagemaker/latest/dg/reinforcement-learning-rl-environments.html) - How to bring your own simulation environment
- [Amazon Kinesis Data Streams Developer Guide](https://docs.aws.amazon.com/streams/latest/dev/introduction.html) - Real-time data ingestion patterns
- [AWS Step Functions Developer Guide](https://docs.aws.amazon.com/step-functions/latest/dg/welcome.html) - Workflow orchestration for ML pipelines
- [DynamoDB Best Practices](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/best-practices.html) - Time-series data patterns for state logging
- [AWS Lambda for ML Inference](https://docs.aws.amazon.com/lambda/latest/dg/lambda-ml.html) - Deploying models for real-time inference

### Research and Background

<!-- TODO (TechWriter): Verify and link specific papers on offline RL for resource allocation -->
<!-- TODO (TechWriter): Verify and link hospital simulation modeling references (discrete-event simulation in healthcare) -->
<!-- TODO (TechWriter): Verify and link Constrained MDP references (CPO, Lagrangian methods) -->

### Healthcare Operations Context

<!-- TODO (TechWriter): Verify AHA or similar source for ED boarding cost statistics -->
<!-- TODO (TechWriter): Verify AHRQ resources on hospital capacity management -->

---

## Estimated Implementation Time

| Phase | Timeline | What You're Building |
|-------|----------|---------------------|
| Basic (simulation only) | 4-6 months | Hospital simulator, basic RL training loop, offline evaluation against historical data. No live integration. Proves feasibility. |
| Production-ready | 12-18 months | Real-time data pipeline, validated simulator, trained and evaluated policy, decision support UI, human workflow integration, monitoring. |
| With variations | 18-24 months | Multi-campus coordination, surge mode, predictive pre-positioning, continuous learning from human feedback. |

---

*← [Main Recipe 15.10](chapter15.10-hospital-resource-allocation-uncertainty) · [Python Example](chapter15.10-python-example) · [Chapter Preface](chapter15-preface)*
