#!/bin/bash
# what of a simulated DAQ is up on this node (one Slurm step)
echo "host=$(hostname) job=$SLURM_JOB_ID step=$SLURM_STEP_ID $(date '+%F %T %Z')"
echo "listening on the DAQ's fixed ports (simxpm 30050/15075, configdb 31050, rundb 31051, frames 31052, control 29985-30045): $(ss -ltn | grep -cE ':(30050|15075|31050|31051|31052|29985|29995|30005|30015|30025|30035|30045) ')"
echo "my procServ processes: $(pgrep -u $USER -x procServ | wc -l); my psdaq.sim processes: $(pgrep -u $USER -f 'psdaq[.]sim[.]' | wc -l); my drp/teb processes: $(pgrep -u $USER -x 'drp|teb' | wc -l)"
ls /dev/datadev* /dev/pcie_adc* /dev/tpr* 2>&1 | head -3
pgrep -u $USER -af 'psdaq[.]sim[.]' | sed 's/^/  /' | cut -c1-138
