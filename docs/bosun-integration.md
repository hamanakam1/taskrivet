# Architectural lessons from Bosun

Decision: Taskrivet is standalone. The experimental Bosun snapshot adapter and UI
were removed at the operator's request. Bosun is not a dependency or backend.

The source review of [Bosun](https://github.com/yetidevworks/bosun/tree/e630cc15dd11f460b50fa070cae7bf0afcc7c124)
informed these design lessons: separate terminal lifecycle from UI lifecycle,
preserve ordered events and reconnect snapshots, distinguish observed activity
from confirmed progress, and test terminal focus and key routing with fake agents.
No Bosun implementation or assets were copied.

Taskrivet now owns PTYs in its own detached local session service. The desktop
reconnects through authenticated Unix-socket IPC. This survives desktop quit, not
service failure or machine reboot. Agent turn completion remains separate from
accepted ticket work.
