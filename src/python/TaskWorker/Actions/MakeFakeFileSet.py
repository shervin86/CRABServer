from TaskWorker.Actions.TaskAction import TaskAction
from TaskWorker.DataObjects.Result import Result

from WMCore.DataStructs.File import File
from WMCore.DataStructs.Fileset import Fileset
from WMCore.DataStructs.Run import Run

from WMCore.Services.SiteDB.SiteDB import SiteDBJSON


class MakeFakeFileSet(TaskAction):
    """This is needed to make WMCore.JobSplitting lib working...
       do not like very much. Given that all is fake here I am
       quite sure we only need total number of events said that I
       set all the other parmas to dummy values. We may want to set
       them in the future"""

    def __init__(self, *args, **kwargs):
        TaskAction.__init__(self, *args, **kwargs)
        self.sbj = SiteDBJSON({"key":self.config.TaskWorker.cmskey,
                          "cert":self.config.TaskWorker.cmscert})


    def getListOfSites(self):
        """ Get the list of sites to use for PrivateMC workflows.
            For the moment we are filtering out T1_ since they are precious resources
            and don't want to overtake production (WMAgent) jobs there. In the
            future we would like to take this list from the SSB.
        """
        sites = self.sbj.getAllCMSNames()
        filteredSites = [site for site in sites if not site.startswith("T1_")]

        return filteredSites


    #even though args is not used we call "handler.actionWork(args, kwargs)" in Handler
    def execute(self, *args, **kwargs): #pylint: disable=unused-argument

        totalevents = kwargs['task']['tm_totalunits']
        firstEvent = 1
        lastEvent = totalevents
        firstLumi = 1
        lastLumi = 10

        # Set a default of 100 events per lumi.  This is set as a task
        # property, as the splitting considers it independently of the file
        # information provided by the fake dataset.
        if not kwargs['task']['tm_events_per_lumi']:
            kwargs['task']['tm_events_per_lumi'] = 100

        #MC comes with only one MCFakeFile
        singleMCFileset = Fileset(name = "MCFakeFileSet")
        newFile = File("MCFakeFile", size = 1000, events = totalevents)
        newFile.setLocation(self.getListOfSites())
        newFile.addRun(Run(1, *range(firstLumi, lastLumi + 1)))
        newFile["block"] = 'MCFakeBlock'
        newFile["first_event"] = firstEvent
        newFile["last_event"] = lastEvent
        singleMCFileset.addFile(newFile)

        return Result(task=kwargs['task'], result=singleMCFileset)

