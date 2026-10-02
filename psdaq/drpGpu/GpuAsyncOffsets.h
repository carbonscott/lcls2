/**
 * @file
 * @brief Register offsets and field extractors for the AxiGpuAsyncCore and PcieAxiVersion firmware blocks. None of these macros is used in psdaq code (pgpread.cc uses one only in a commented-out line).
 */
#pragma once

/*****************************************************************
 * AxiGpuAsyncCore
 *****************************************************************/

/** Common registers **/

#define GPU_ASYNC_INFO1_REG					0x4
/** Extract bits 7-0 of an INFO1 register value; meaning inferred from the name; not verified. */
#define GPU_ASYNC_INFO1_ARCACHE(_val)		((_val) & 0xFF)
/** Extract bits 15-8 of an INFO1 register value; meaning inferred from the name; not verified. */
#define GPU_ASYNC_INFO1_AWCACHE(_val)		(((_val) >> 8) & 0xFF)
/** Extract bits 23-16 of an INFO1 register value; meaning inferred from the name; not verified. */
#define GPU_ASYNC_INFO1_BYTES(_val)			(((_val) >> 16) & 0xFF)
/** Extract bits 28-24 (5 bits) of an INFO1 register value; meaning inferred from the name; not verified. */
#define GPU_ASYNC_INFO1_MAX_BUFFERS(_val)	(((_val) >> 24) & 0x1F)	/* 5 bits */

/** Offset 0x8 of the INFO2 register in the AxiGpuAsyncCore block (per the section comment). */
#define GPU_ASYNC_INFO2_REG					0x8
/** Extract bits 7-0 of an INFO2 register value; meaning inferred from the name; not verified. */
#define GPU_ASYNC_INFO2_WR_CNT(_val)		((_val) & 0xFF)
/** Extract bits 15-8 of an INFO2 register value; meaning inferred from the name; not verified. */
#define GPU_ASYNC_INFO2_WR_EN(_val)			(((_val) >> 8) & 0xFF)
/** Extract bits 23-16 of an INFO2 register value; meaning inferred from the name; not verified. */
#define GPU_ASYNC_INFO2_RD_CNT(_val)		(((_val) >> 16) & 0xFF)
/** Extract bits 31-24 of an INFO2 register value; meaning inferred from the name; not verified. */
#define GPU_ASYNC_INFO2_RD_EN(_val)			(((_val) >> 24) & 0xFF)

/** Register offset 0x10; a receive frame counter, inferred from the name; not verified. */
#define GPU_ASYNC_RX_FRAME_CNT				0x10
/** Register offset 0x14; a transmit frame counter, inferred from the name; not verified. */
#define GPU_ASYNC_TX_FRAME_CNT				0x14
/** Register offset 0x18; a write error counter, inferred from the name; not verified. */
#define GPU_ASYNC_WR_ERR_CNT				0x18
/** Register offset 0x1C; a read error counter, inferred from the name; not verified. */
#define GPU_ASYNC_RD_ERR_CNT				0x1C

/** Register offset 0x20; a counter reset, inferred from the name; not verified. */
#define GPU_ASYNC_CNT_RST					0x20

/** Write addresses and sizes [Starts at 0x100] **/
#define GPU_ASYNC_WR_ADDR(_n)				(0x100 | ((_n) << 4))
/** Offset of the write size register of buffer _n: 0x108 plus 16 per buffer (per the section comment on write addresses and sizes). */
#define GPU_ASYNC_WR_SIZE(_n)				(0x108 | ((_n) << 4))

/** Read addresses [Starts at 0x200] **/
#define GPU_ASYNC_RD_ADDR(_n)				(0x200 | ((_n) << 4))

/** Write enable bit [Starts at 0x300] **/
#define GPU_ASYNC_WR_ENABLE(_n) 			(0x300 | ((_n) * 4))

/** Read enable bit [Starts at 0x400] **/
#define GPU_ASYNC_RD_ENABLE(_n) 			(0x400 | ((_n) * 4))
/** Offset 0x400 plus 4 per buffer _n; the same value as GPU_ASYNC_RD_ENABLE(_n). */
#define GPU_ASYNC_RD_SIZE(_n)	 			(0x400 | ((_n) * 4))

/** I/O Stats [Starts at 0x500] **/
#define GPU_ASYNC_TOTAL_LATENCY(_n) 		(0x500 + (_n*16))
/** Offset 0x504 plus 16 per index _n in the I/O statistics area (per the section comment); _n is not parenthesized in the expansion. */
#define GPU_ASYNC_GPU_LATENCY(_n) 			(0x504 + (_n*16))
/** Offset 0x508 plus 16 per index _n in the I/O statistics area (per the section comment); _n is not parenthesized in the expansion. */
#define GPU_ASYNC_WR_LATENCY(_n)			(0x508 + (_n*16))
/** Offset 0x50C plus 16 per index _n in the I/O statistics area (per the section comment); _n is not parenthesized in the expansion. */
#define GPU_ASYNC_RD_LATENCY(_n)			(0x50C + (_n*16))

/** Max buffers, must match firmware value **/
#define MAX_BUFFERS                         8


/*****************************************************************
 * AxiPcieCore
 *****************************************************************/

/** Offset 0x20000 of the AxiPcieCore version block (per the section comments). */
#define PCIE_AXI_VERSION_OFFSET             0x20000

/*****************************************************************
 * PcieAxiVersion
 *****************************************************************/

/** Offset 0x4 in the PcieAxiVersion block; a scratchpad register, inferred from the name; not verified. */
#define PCIE_AXI_VERSION_SCRATCHPAD         0x4
/** Offset 0x420 in the PcieAxiVersion block; a clock frequency register, inferred from the name; not verified. */
#define PCIE_AXI_VERSION_CLK_FREQ           (0x400+(4*8))
