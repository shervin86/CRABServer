from __future__ import division
from __future__ import absolute_import
import time
import bisect
import random

import classad
import htcondor
import HTCondorUtils

CollectorCache = {}
# From http://stackoverflow.com/questions/3679694/a-weighted-version-of-random-choice
def weighted_choice(choices):
    values, weights = list(zip(*choices))
    total = 0
    cum_weights = []
    for w in weights:
        total += w
        cum_weights.append(total)
    x = random.random() * total
    i = bisect.bisect(cum_weights, x)
    return values[i]

def filterScheddsByClassAds(schedds, classAds, logger=None):
    """ Check a list of schedds for missing classAds
        Used when choosing a schedd to see if each schedd has the needed classads defined.
        Return a list of valid schedds to choose from
    """

    validSchedds = []

    # Create a list of schedds to be ignored
    for schedd in schedds:
        scheddValid = True
        for classAd in classAds:
            if classAd not in schedd:
                if logger:
                    logger.debug("Ignoring %s schedd since it is missing the %s ClassAd." % (schedd['Name'], classAd))
                scheddValid = False
        if scheddValid:
            validSchedds.append(schedd)

    return validSchedds

def capacityMetricsChoicesHybrid(schedds, goodSchedds, logger=None):
    """ Mix of Jadir's way and Marco's way.
        Return a list of scheddobj and the weight to be used in the weighted choice.
        If all of the schedds are full, pick randomly from the ones in the REST config.
    """

    classAdsRequired = ['DetectedMemory', 'TotalFreeMemoryMB', 'MaxJobsRunning', 'TotalRunningJobs', 'TransferQueueMaxUploading', 'TransferQueueNumUploading', 'Name']
    schedds = filterScheddsByClassAds(schedds, classAdsRequired, logger)

    # Get only those schedds that are in our external rest configuration and their status is ok
    schedds = [schedd for schedd in schedds if schedd['Name'] in goodSchedds and classad.ExprTree.eval(schedd['IsOk'])]

    totalMemory = totalJobs = totalUploads = 0
    for schedd in schedds:
        totalMemory += schedd['DetectedMemory']
        totalJobs += schedd['MaxJobsRunning']
        totalUploads += schedd['TransferQueueMaxUploading']

    logger.debug("Total Mem: %d, Total Jobs: %d, Total Uploads: %d" % (totalMemory, totalJobs, totalUploads))
    weights = {}
    for schedd in schedds:
        memPerc = schedd['TotalFreeMemoryMB']/totalMemory
        jobPerc = (schedd['MaxJobsRunning']-schedd['TotalRunningJobs'])/totalJobs
        uplPerc = (schedd['TransferQueueMaxUploading']-schedd['TransferQueueNumUploading'])/totalUploads
        weight = min(memPerc, uplPerc, jobPerc)
        weights[schedd['Name']] = weight
        logger.debug("%s: Mem %d, MemPrct %0.2f, Run %d, RunPrct %0.2f, Trf %d, TrfPrct %0.2f, weight: %f" %
                    (schedd['Name'], schedd['TotalFreeMemoryMB'], memPerc,
                     schedd['JobsRunning'], jobPerc,
                     schedd['TransferQueueNumUploading'], uplPerc, weight))

    if schedds:
        choices = [(schedd['Name'], weights[schedd['Name']]) for schedd in schedds]
    else:
        # In case the query to the collector doesn't return any schedds,
        # for example when all of them are full of tasks.
        # Pick from the schedds in the good schedulers list with equal weights.
        choices = [(schedd, 1) for schedd in goodSchedds]
    return choices

def memoryBasedChoices(schedds, goodSchedds, logger=None):
    """ Choose the schedd based on the DetectedMemory classad present in the schedds object
        Return a list of scheddobj and the weight to be used in the weighted choice
    """
    schedds_dict = {}
    for schedd in schedds:
        if 'DetectedMemory' in schedd and 'Name' in schedd:
            schedds_dict[schedd['Name']] = schedd['DetectedMemory']
    choices = [(i, schedds_dict.get(i, 24 * 1024)) for i in goodSchedds]
    return choices


class HTCondorLocator(object):

    def __init__(self, config, logger=None):
        self.config = config
        self.logger = logger


    def adjustWeights(self, choices):
        """ The method iterates over the htcondorSchedds dict from the REST and ajust schedds
            weights based on the weightfactor key.

            param choices: a list containing schedds and their weight, such as
                        [(u'crab3-5@vocms05.cern.ch', 24576), (u'crab3-5@vocms059.cern.ch', 23460L)]
        """

        i = 0
        for schedd, weight in choices:
            newweight = weight * self.config['htcondorSchedds'].get(schedd, {}).get("weightfactor", 1)
            choices[i] = (schedd, newweight)
            i += 1


    def getSchedd(self, chooserFunction=memoryBasedChoices):
        """
        Determine a schedd to use for this task.
        """
        collector = self.getCollector()

        htcondor.param['COLLECTOR_HOST'] = collector.encode('ascii', 'ignore')
        coll = htcondor.Collector()
        schedds = coll.query(htcondor.AdTypes.Schedd, 'StartSchedulerUniverse =?= true && CMSGWMS_Type=?="crabschedd"',
                             ['Name', 'DetectedMemory','TotalFreeMemoryMB','TransferQueueNumUploading', 'TransferQueueMaxUploading',
                             'TotalRunningJobs', 'JobsRunning','MaxJobsRunning', 'IsOK'])
        if self.config and "htcondorSchedds" in self.config:
            choices = chooserFunction(schedds, self.config['htcondorSchedds'], self.logger)
            self.adjustWeights(choices)
        schedd = weighted_choice(choices)
        return schedd

    def getScheddObjNew(self, schedd):
        """
        Return a tuple (schedd, address) containing an object representing the
        remote schedd and its corresponding address.
        """
        htcondor.param['COLLECTOR_HOST'] = self.getCollector().encode('ascii', 'ignore')
        coll = htcondor.Collector()
        schedds = coll.query(htcondor.AdTypes.Schedd, 'Name=?=%s' % HTCondorUtils.quote(schedd.encode('ascii', 'ignore')),
                             ["AddressV1", "CondorPlatform", "CondorVersion", "Machine", "MyAddress", "Name", "MyType", "ScheddIpAddr", "RemoteCondorSetup"])
        self.scheddAd = ""
        if not schedds:
            self.scheddAd = self.getCachedCollectorOutput(schedd)
        else:
            self.cacheCollectorOutput(schedd, schedds[0])
            self.scheddAd = self.getCachedCollectorOutput(schedd)
        address = self.scheddAd['MyAddress']
        scheddObj = htcondor.Schedd(self.scheddAd)
        return scheddObj, address

    def cacheCollectorOutput(self, cacheName, output):
        """
        Saves Collector output in tmp directory.
        """
        global CollectorCache
        if cacheName in CollectorCache.keys():
            CollectorCache[cacheName]['ScheddAds'] = output
        else:
            CollectorCache[cacheName] = {}
            CollectorCache[cacheName]['ScheddAds'] = output
        CollectorCache[cacheName]['updated'] = int(time.time())

    def getCachedCollectorOutput(self, cacheName):
        """
        Return cached Collector output if they exist.
        """
        global CollectorCache
        now = int(time.time())
        if cacheName in CollectorCache.keys():
            if (now - CollectorCache[cacheName]['updated']) < 1800:
                return CollectorCache[cacheName]['ScheddAds']
            else:
                raise Exception("Unable to contact the collector and cached results are too old for using.")
        else:
            raise Exception("Unable to contact the collector and cached results does not exist for %s" % cacheName)

    def getCollector(self, name="localhost"):
        """
        Return an object representing the collector given the pool name.
        """
        if self.config and "htcondorPool" in self.config:
            return self.config["htcondorPool"]
        return name

