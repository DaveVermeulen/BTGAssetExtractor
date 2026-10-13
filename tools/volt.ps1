<#
  VOLT archive reader for BIONICLE: The Game (.vol / .avl).
  Opens archives read-only. Usage:
    . .\tools\volt.ps1
    Get-VoltEntries <archive>                       # list entries
    Export-VoltEntries <archive> <outDir>           # extract all entries

  Layout (little-endian), as observed:
    0x00 char[4] "VOLT"
    0x04 u32     version (2)
    0x08 u32     entry count N
    0x0C u32     size of record block in bytes
    0x10 N x { u32 nameHash; u32 unknown (1); u32 recordOffset }   sorted by hash
    then record block, each record:
         u32 dataOffset; u32 unknown; u32 dataSize; u32 unknown; char name[] (NUL-terminated)
    data is aligned to 0x800 (2048-byte sectors), padding bytes are 'i' (0x69).
#>

function Get-VoltEntries([string]$Path) {
    $fs = [IO.File]::Open($Path, 'Open', 'Read', 'Read')
    try {
        $br = New-Object IO.BinaryReader($fs)
        $magic = -join ($br.ReadBytes(4) | ForEach-Object { [char]$_ })
        if ($magic -ne 'VOLT') { throw "$Path is not a VOLT archive" }
        $version = $br.ReadUInt32(); $count = $br.ReadUInt32(); $recSize = $br.ReadUInt32()
        $index = for ($i = 0; $i -lt $count; $i++) {
            [pscustomobject]@{ Hash = $br.ReadUInt32(); Unk = $br.ReadUInt32(); RecOff = $br.ReadUInt32() }
        }
        $recBase = 16 + 12 * $count
        $recs = $br.ReadBytes($recSize)
        foreach ($e in $index) {
            $o = $e.RecOff
            $off = [BitConverter]::ToUInt32($recs, $o); $u1 = [BitConverter]::ToUInt32($recs, $o + 4)
            $size = [BitConverter]::ToUInt32($recs, $o + 8); $u2 = [BitConverter]::ToUInt32($recs, $o + 12)
            $end = [Array]::IndexOf($recs, [byte]0, $o + 16)
            $name = [Text.Encoding]::ASCII.GetString($recs, $o + 16, $end - $o - 16)
            [pscustomobject]@{
                Archive = [IO.Path]::GetFileName($Path); Name = $name; Offset = $off; Size = $size
                Unk1 = $u1; Unk2 = $u2; Hash = ('{0:X8}' -f $e.Hash)
            }
        }
    } finally { $fs.Close() }
}

function Export-VoltEntries([string]$Path, [string]$OutDir) {
    New-Item -ItemType Directory -Force $OutDir | Out-Null
    $fs = [IO.File]::Open($Path, 'Open', 'Read', 'Read')
    try {
        foreach ($e in Get-VoltEntries $Path) {
            $buf = New-Object byte[] $e.Size
            $fs.Seek($e.Offset, 'Begin') | Out-Null
            [void]$fs.Read($buf, 0, $e.Size)
            $dest = Join-Path $OutDir $e.Name
            New-Item -ItemType Directory -Force (Split-Path $dest) | Out-Null
            [IO.File]::WriteAllBytes($dest, $buf)
        }
    } finally { $fs.Close() }
}
