/* STM32F103C8, HSI 8 MHz. Signal pins and servo travel are listed in hardware/wiring.md. */
#include <stdint.h>
#include <stdio.h>
#include "wire.h"

#define R(a) (*(volatile uint32_t *)(a))
#define GPIOA 0x40010800u
#define GPIOB 0x40010c00u
#define TIM3 0x40000400u
#define UART 0x40013800u
#define GATE_CLOSED_US 1000u
#define GATE_OPEN_US 1600u
#define LEFT_US 1100u
#define RIGHT_US 1900u

volatile uint32_t ld_ms;
static LdCell cell;
void SysTick_Handler(void) { ld_ms++; }

static void outputs(void) {
    R(TIM3+0x34) = ld_gate_open(&cell) ? GATE_OPEN_US : GATE_CLOSED_US;
    R(TIM3+0x38) = cell.route ? RIGHT_US : LEFT_US;
}
static void send_status(uint32_t seq, unsigned result, uint32_t inputs) {
    char body[150], line[170];
    int n = snprintf(body, sizeof body, "%lu,%u,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%lu",
        (unsigned long)seq,result,(unsigned long)cell.session,(unsigned long)cell.job,
        (unsigned long)cell.state,(unsigned long)cell.fault,(unsigned long)cell.route,
        (unsigned long)inputs,(unsigned long)cell.releases,(unsigned long)cell.completed,(unsigned long)ld_ms);
    if (n < 0 || n >= (int)sizeof body) return;
    snprintf(line,sizeof line,"@%s*%04X\n",body,ld_crc(body,(uint32_t)n));
    for (char *p=line; *p; p++) { while (!(R(UART)&(1u<<7))) {} R(UART+4)=(unsigned char)*p; }
}
static void hardware_init(void) {
    R(0x40021018) |= (1u<<0)|(1u<<2)|(1u<<3)|(1u<<14); /* AFIO GPIOA GPIOB USART1 */
    R(0x4002101c) |= 1u<<1; /* TIM3 */
    // PA0/1/2: pull-up inputs; PA6/7: timer PWM. NC emergency loop lives on PB0.
    R(GPIOA) = (R(GPIOA)&~0xff000fffu)|0xbb000888u;
    R(GPIOA+0x0c) |= 7;
    R(GPIOB) = (R(GPIOB)&~0xffu)|0x88u;
    R(GPIOB+0x0c) |= 3;
    R(GPIOA+4) = (R(GPIOA+4)&~0xff0u)|0x4b0u;
    R(UART+8)=69; /* 8 MHz / 115200; actual baud approx 115942 */
    R(UART+0x0c)=(1u<<13)|(1u<<3)|(1u<<2);
    R(TIM3+0x28)=7; R(TIM3+0x2c)=19999; /* 1 MHz timer, 50 Hz servos */
    R(TIM3+0x18)=(6u<<4)|(1u<<3)|(6u<<12)|(1u<<11);
    R(TIM3+0x20)=0x11; outputs(); R(TIM3+0x14)=1; R(TIM3)=(1u<<7)|1;
    R(0xe000e014)=7999; R(0xe000e018)=0; R(0xe000e010)=7;
    R(0x40003000)=0x5555; R(0x40003004)=4; R(0x40003008)=625;
    R(0x40003000)=0xcccc; R(0x40003000)=0xaaaa;
}
int main(void) {
    ld_init(&cell); hardware_init();
    char line[101]; unsigned used=0, overflow=0;
    uint32_t last=0, stable=0, raw_prev=0, changed=0;
    for (;;) {
        uint32_t now=ld_ms;
        uint32_t raw=(~R(GPIOA+8))&7u;
        uint32_t estop=R(GPIOB+8)&1u; /* Open wire is a stop request. */
        if (raw!=raw_prev) { changed=now; raw_prev=raw; }
        if ((uint32_t)(now-changed)>=15) stable=raw;
        if ((uint32_t)(now-last)>=1) {
            last=now; ld_tick(&cell,now,stable,estop); outputs();
            R(0x40003000)=0xaaaa;
        }
        uint32_t sr=R(UART);
        if (sr&((1u<<5)|(1u<<3))) {
            char ch=(char)R(UART+4);
            if (sr&(1u<<3)) { overflow=1; used=0; }
            if (ch=='\n') {
                line[used]=0;
                LdCommand cmd;
                if (!overflow && ld_parse(line,&cmd)) {
                    unsigned result;
                    // ARM 必须同时按住本地确认按钮，旧串口数据不能独自解除上电锁定。
                    if (cmd.op==LD_ARM && (R(GPIOB+8)&2u)) result=LD_BLOCKED;
                    else result=(unsigned)ld_dispatch(&cell,&cmd,now,stable,estop);
                    outputs(); send_status(cmd.seq,result,stable);
                }
                used=0; overflow=0;
            } else if (ch!='\r') {
                if (used<sizeof line-1 && !overflow) line[used++]=ch;
                else { used=0; overflow=1; }
            }
        }
    }
}
