正式轮（20260918-1822）：operator-run.md + wizard-full.log（首装 18 秒；操作员 1 次误输入触发“其它键=安全退出”零改动后一次重跑成功，全程如实记录）；quickfirst-docker-123.log（工程预跑 rc=0，smoke 22/22）。
机械轮（20260918-1653）：testA-mechanical-first.log / testB-existing.log / testB-upgrade-dup.log / testC-wizard.log / testD-wizard.log / testF-rollback.log / testG-backup-restore.log / restart-autostart.log / testB-seed-smoke.log。
心跳：坏镜像就绪等待 180 秒期间每 15 秒输出“已等待 n 秒”；正常快环境最大静默 ≤10 秒，无 >30 秒无输出。
