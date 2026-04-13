.PHONY: init deploy clean bootstrap fetch-schemas generate-mock unpack-mock \
        package-extract package-compact package-nlq package-lambdas test-pipeline \
        enrich-schemas index-schemas nlq nlq-api api-key help

# Knobs (override on the command line, e.g. `make generate-mock ACCOUNTS=50`)
AWS_REGION      ?= eu-west-2
MOCK_BUCKET     ?= cinq-config-mock
CONFIG_BUCKET   ?= cinq-config
PROFILE         ?= compute
ACCOUNTS        ?= 500
VPCS            ?= 3
SEED            ?= 42
SCHEMAS_DIR     ?= data/config_resource_schemas
PROFILES_FILE   ?= scripts/config_profiles.json
TEST_TIMEOUT    ?= 360

all: init deploy

init:
	@echo "Initializing Terraform..."
	terraform -chdir=terraform/app init

package-extract:
	@echo "Packaging extract Lambda..."
	@mkdir -p build
	@# archive_file data source handles the actual zip during terraform apply,
	@# but create the directory here so manual invocations don't fail.

package-compact:
	@echo "Packaging compact Lambda..."
	@mkdir -p build

# Bundle the NLQ Lambda: handler + boto3>=1.42 (for s3vectors) + the
# enriched schema markdown docs. Idempotent re-run-safe.
package-nlq:
	@echo "Packaging NLQ HTTP API Lambda..."
	./scripts/package_nlq_lambda.sh

package-lambdas: package-extract package-compact package-nlq

deploy: package-lambdas
	@echo "Deploying infrastructure..."
	terraform -chdir=terraform/app apply -auto-approve

# Fetch AWS Config resource schemas from awslabs (skipped if already present)
fetch-schemas:
	@if [ -d "$(SCHEMAS_DIR)" ] && [ -n "$$(ls -A $(SCHEMAS_DIR) 2>/dev/null)" ]; then \
		echo "Schemas already present in $(SCHEMAS_DIR) — skipping fetch."; \
	else \
		echo "Fetching AWS Config resource schemas..."; \
		./scripts/fetch_config_resource_schemas.sh $(SCHEMAS_DIR); \
	fi

# Generate mock AWS Config snapshots and upload to the mock bucket
generate-mock: fetch-schemas
	@echo "Generating mock Config data ($(PROFILE) profile, $(ACCOUNTS) accounts) into s3://$(MOCK_BUCKET)/"
	./scripts/generate_config_snapshot.py \
		--s3-bucket $(MOCK_BUCKET) \
		--schemas-dir $(SCHEMAS_DIR) \
		--profiles-file $(PROFILES_FILE) \
		--profile $(PROFILE) \
		--num-accounts $(ACCOUNTS) \
		--vpcs $(VPCS) \
		--region $(AWS_REGION) \
		--seed $(SEED)

# Dev-time only: unpack gzipped snapshots locally (pre-Lambda pipeline workflow).
unpack-mock:
	@echo "Unpacking today's snapshots from s3://$(MOCK_BUCKET)/ to s3://$(CONFIG_BUCKET)/"
	./scripts/unpack_config_snapshots.py \
		--src-bucket $(MOCK_BUCKET) \
		--dst-bucket $(CONFIG_BUCKET) \
		--region $(AWS_REGION)

bootstrap: generate-mock
	@echo "Bootstrap complete — the extract Lambda will process the snapshots via SQS."

# End-to-end live test: regenerate mock data, wait for the extract Lambda to
# drain the queue, then query Athena to prove the rows landed in the view.
test-pipeline: generate-mock
	./scripts/test_pipeline.sh $(TEST_TIMEOUT)

# ---- Phase 2: schema RAG ----

# One-off Claude enrichment of every raw resource schema into a semantic
# Markdown doc. Idempotent — re-runs skip files that already exist unless
# you pass FORCE=1.
enrich-schemas:
	@echo "Enriching $(SCHEMAS_DIR) into data/enriched_schemas/..."
	./scripts/enrich_schemas.py $(if $(FORCE),--force) $(if $(LIMIT),--limit $(LIMIT))

# One-off Titan embedding of every enriched doc, upserted into S3 Vectors.
index-schemas:
	@echo "Embedding enriched schemas and upserting into S3 Vectors..."
	./scripts/index_schemas.py

# Natural-language query CLI. Pass Q="..." for the question.
# Examples:
#   make nlq Q="how many EC2 instances per account, top 10"
#   make nlq Q="find encrypted EBS volumes" NLQ_ARGS="--explain --top-k 8"
#   make nlq Q="drop the operational table" NLQ_ARGS="--dry-run"
nlq:
	@if [ -z "$(Q)" ]; then echo 'usage: make nlq Q="<question>" [NLQ_ARGS="..."]'; exit 2; fi
	./scripts/nlq.py $(NLQ_ARGS) "$(Q)"

# Print the NLQ API key from Secrets Manager so you can stick it in $X_API_KEY.
api-key:
	@aws secretsmanager get-secret-value \
		--secret-id $$(terraform -chdir=terraform/app output -raw nlq_api_key_secret_arn) \
		--query SecretString --output text

# Curl the deployed HTTP API. Pass Q="..." for the question.
nlq-api:
	@if [ -z "$(Q)" ]; then echo 'usage: make nlq-api Q="<question>"'; exit 2; fi
	@key=$$(aws secretsmanager get-secret-value \
		--secret-id $$(terraform -chdir=terraform/app output -raw nlq_api_key_secret_arn) \
		--query SecretString --output text); \
	endpoint=$$(terraform -chdir=terraform/app output -raw nlq_api_endpoint); \
	echo "POST $$endpoint"; \
	curl -sS -X POST "$$endpoint" \
		-H "x-api-key: $$key" \
		-H 'content-type: application/json' \
		-d "$$(jq -nc --arg q '$(Q)' '{question:$$q}')" | jq

clean:
	@echo "Cleaning up..."
	rm -f terraform/app/.terraform.lock.hcl
	rm -rf terraform/app/.terraform
	rm -rf build

help:
	@echo "Available targets:"
	@echo "  init           - Initialize Terraform"
	@echo "  deploy         - Deploy infrastructure (packages Lambdas as a prerequisite)"
	@echo "  fetch-schemas  - Download AWS Config resource schemas (skipped if present)"
	@echo "  generate-mock  - Generate mock Config data into the mock bucket"
	@echo "  bootstrap      - fetch-schemas + generate-mock (pipeline processes asynchronously)"
	@echo "  test-pipeline  - generate-mock + wait for SQS drain + assert rows via Athena"
	@echo "  unpack-mock    - Dev-time local unpack (pre-pipeline workflow)"
	@echo "  enrich-schemas - One-off Claude enrichment of raw schemas (FORCE=1, LIMIT=N)"
	@echo "  index-schemas  - Embed enriched schemas with Titan, upsert into S3 Vectors"
	@echo "  nlq            - Local NL query via scripts/nlq.py. Usage: make nlq Q='<question>' [NLQ_ARGS='--explain --dry-run']"
	@echo "  nlq-api        - Curl the deployed HTTP API. Usage: make nlq-api Q='<question>'"
	@echo "  api-key        - Print the NLQ API key from Secrets Manager"
	@echo "  clean          - Remove local Terraform state/cache and build artifacts"
	@echo "  all            - Run init and deploy"
	@echo ""
	@echo "Knobs (override on the command line):"
	@echo "  PROFILE=$(PROFILE) ACCOUNTS=$(ACCOUNTS) VPCS=$(VPCS) SEED=$(SEED)"
	@echo "  MOCK_BUCKET=$(MOCK_BUCKET) CONFIG_BUCKET=$(CONFIG_BUCKET) AWS_REGION=$(AWS_REGION)"
	@echo "  TEST_TIMEOUT=$(TEST_TIMEOUT)"
