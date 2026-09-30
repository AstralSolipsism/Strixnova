from pathlib import Path
import json,os,sys
from strixnova.project_maintenance import project_operation
project=Path(sys.argv[1])
print(json.dumps({"pid":os.getpid(),"script":"owned_interrupted_writer.py","explicit_child_launches":0}),flush=True)
with project_operation(project,operation_name="fixed-maintenance-output"):
    output=project/".strixnova/artifacts/fixed-business-output.txt"
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open("ab") as stream:
        stream.write(b"business-effect: recorded-once\n")
        stream.flush()
        os.fsync(stream.fileno())
    os._exit(23)
