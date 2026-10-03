module "packaging" {
  source = "./modules/archives"
}

module "intake" {
  source       = "./modules/intake"
  archive_path = module.packaging.intake_archive_path
}

module "reports" {
  source       = "./modules/reports"
  archive_path = module.packaging.reports_archive_path
}
