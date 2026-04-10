.PHONY: init deploy clean help

all: init deploy

init:
	@echo "Initializing Terraform..."
	cd terraform/app && terraform init

deploy:
	@echo "Deploying infrastructure..."
	cd terraform/app && terraform apply -auto-approve

clean:
	@echo "Cleaning up..."
	rm -f terraform/app/.terraform.lock.hcl
	rm -rf terraform/app/.terraform

help:
	@echo "Available targets:"
	@echo "  init    - Initialize Terraform"
	@echo "  deploy  - Deploy infrastructure"
	@echo "  clean   - Remove local Terraform state/cache"
	@echo "  all     - Run init and deploy"
