#!/bin/sh
echo "Beginning dag_boostrap_startup.sh at $(date)"
set -x

# Touch a bunch of files to make sure job doesn't go on hold for missing files
for FILE in $1.dagman.out RunJobs.dag RunJobs.dag.dagman.out RunJobs.dag.rescue.001 dbs_discovery.err dbs_discovery.out job_splitting.err job_splitting.out; do
    touch $FILE
done

# Bootstrap the HTCondor environment
if [ "X$_CONDOR_JOB_AD" != "X" ];
then
    source_script=`grep '^RemoteCondorSetup =' $_CONDOR_JOB_AD | tr -d '"' | awk '{print $NF;}'`
    if [ "X$source_script" != "X" ] && [ -e $source_script ];
    then
        source $source_script
    fi
fi

export _CONDOR_DAGMAN_LOG=$PWD/$1.dagman.out
export _CONDOR_MAX_DAGMAN_LOG=0

CONDOR_VERSION=`condor_version | head -n 1`
PROC_ID=`grep '^ProcId =' $_CONDOR_JOB_AD | tr -d '"' | awk '{print $NF;}'`
CLUSTER_ID=`grep '^ClusterId =' $_CONDOR_JOB_AD | tr -d '"' | awk '{print $NF;}'`
export CONDOR_ID="${CLUSTER_ID}.${PROC_ID}"

condor_dagman -f -l . -Lockfile $PWD/$1.lock -AutoRescue 1 -DoRescueFrom 0 -Dag $PWD/$1 -Suppress_notification -Dagman `which condor_dagman` -CsdVersion "$CONDOR_VERSION"
set +x
EXIT_STATUS=$?

# We do this after the job because dagman will cowardly refuse to overwrite any pre-existing file, even if it's empty
touch $1.rescue.001

exit $EXIT_STATUS