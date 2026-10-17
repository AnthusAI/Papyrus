import { Duration, RemovalPolicy } from "aws-cdk-lib";
import * as backup from "aws-cdk-lib/aws-backup";
import * as events from "aws-cdk-lib/aws-events";
import type * as s3 from "aws-cdk-lib/aws-s3";
import type { Construct } from "constructs";

export type StorageBackupsProps = {
  storageBucket: s3.IBucket;
  backupVaultName: string;
};

/**
 * Adds the resources directly to `scope` (no wrapper construct) so the logical
 * ids of the live p.apyr.us backup stack stay unchanged.
 */
export function addStorageBackups(scope: Construct, props: StorageBackupsProps) {
  const vault = new backup.BackupVault(scope, "PapyrusStorageBackupVault", {
    backupVaultName: props.backupVaultName,
    removalPolicy: RemovalPolicy.RETAIN,
  });
  const plan = new backup.BackupPlan(scope, "PapyrusStorageBackupPlan", {
    backupVault: vault,
  });

  plan.addRule(
    new backup.BackupPlanRule({
      ruleName: "papyrus-storage-pitr-35d",
      enableContinuousBackup: true,
      deleteAfter: Duration.days(35),
    }),
  );

  plan.addRule(
    new backup.BackupPlanRule({
      ruleName: "papyrus-storage-daily-365d",
      scheduleExpression: events.Schedule.cron({ minute: "0", hour: "5" }),
      deleteAfter: Duration.days(365),
    }),
  );

  plan.addSelection("PapyrusStorageBackupSelection", {
    allowRestores: true,
    resources: [backup.BackupResource.fromArn(props.storageBucket.bucketArn)],
  });

  return { plan, vault };
}
