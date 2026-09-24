export const dropdownMenu = {
	name: 'dropdown-menu',
	props: {
		label: String,
		items: Array, // [{text, value}] or strings
		alignRight: { type: Boolean, default: false },
	},
	emits: ['select'],
	data(){ return {
		open: false,
		activeIndex: -1,
		computedAlignRight: false,
	}},
	methods: {
		toggle(e){
			if(this.open){ this.close(); return; }
			this.open = true;
			this.activeIndex = -1;
			this.computedAlignRight = this.alignRight || e.target.getBoundingClientRect().left > window.innerWidth / 2;
			document.addEventListener('keydown', this._keydown ??= this.keydown.bind(this));
			this.$nextTick(() => {
				document.addEventListener('click', this._clickOutside ??= this.clickOutside.bind(this));
			});
		},
		close(){
			this.open = false;
			this.activeIndex = -1;
			document.removeEventListener('keydown', this._keydown);
			document.removeEventListener('click', this._clickOutside);
		},
		select(item, index){
			this.$emit('select', item, index);
			this.close();
		},
		clickOutside(e){
			if(!this.$el.contains(e.target)) this.close();
		},
		keydown(e){
			const count = this.items.length;
			if(e.key === 'ArrowDown'){
				e.preventDefault();
				this.activeIndex = (this.activeIndex + 1) % count;
				this.$nextTick(() => {
					this.$el.querySelector('.menu-item.active')?.scrollIntoView({block: 'nearest'});
				});
			} else if(e.key === 'ArrowUp'){
				e.preventDefault();
				this.activeIndex = (this.activeIndex - 1 + count) % count;
				this.$nextTick(() => {
					this.$el.querySelector('.menu-item.active')?.scrollIntoView({block: 'nearest'});
				});
			} else if(e.key === 'Enter'){
				e.preventDefault();
				if(this.activeIndex >= 0) this.select(this.items[this.activeIndex], this.activeIndex);
			} else if(e.key === 'Escape'){
				e.preventDefault();
				this.close();
			}
		},
	},
	beforeUnmount(){
		if(this._keydown) document.removeEventListener('keydown', this._keydown);
		if(this._clickOutside) document.removeEventListener('click', this._clickOutside);
	},
	template: `<div class="menu">
		<div class="menu-trigger" :class="{open}" @click="toggle($event)"><slot name="trigger">{{ label }}</slot></div>
		<div class="menu-dropdown" :class="{open, 'align-right': computedAlignRight}">
			<div class="menu-item" v-for="(item, i) in items" :class="{active: activeIndex === i}" @mousemove="activeIndex = i" @mouseleave="activeIndex = -1" @click="select(item, i)"><slot name="item" :item="item" :index="i">{{ typeof item === 'string' ? item : item.text }}</slot></div>
		</div>
	</div>`,
};
