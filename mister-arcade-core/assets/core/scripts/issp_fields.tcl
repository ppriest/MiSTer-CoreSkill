# The field tables for this core's ISSP probes, read by the MCP's read_issp.tcl and
# probe_sequence. One table per instance id, `set fields_<id> {{name lo hi format} ...}`;
# format is dec, sdec (signed 16), hex or bit. Bit numbers index the probe bus as the RTL
# concatenates it (the issp instance in the top-level .sv): keep them in step with it, a
# silently shifted field decodes as plausible nonsense. By convention source bit 0 pulsed
# is the counter clear. Instances sharing a layout: `set fields_B $fields_A`. A build whose
# bus for an instance has another width: `set fields_<id>_w<bits> {...}`, used at that width.
set fields_F {
    {frames           0  15 dec}
    {pll_locked     127 127 bit}
}
